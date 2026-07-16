package com.stock.research

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** UI state for the dashboard screen. */
data class DashboardState(
    val recipient: String? = null,
    val notes: List<StockClient.NoteSummary> = emptyList(),
    val deepResearch: List<StockClient.NoteSummary> = emptyList(),
    val selected: StockClient.NoteDetail? = null,
    val loading: Boolean = false,
    val sending: Boolean = false,
    val errorMessage: String? = null,
    val replyStatus: String? = null,
    val lastRefreshedAt: Long = 0L,
    // F18b: image upload state
    val uploadingImage: Boolean = false,
    val uploadStatus: String? = null,
)

class StockViewModel(private val client: StockClient) : ViewModel() {

    private val _state = MutableStateFlow(DashboardState())
    val state: StateFlow<DashboardState> = _state.asStateFlow()

    private var pollJob: Job? = null
    private var fastPollJob: Job? = null
    private val deepResearchKinds = listOf(
        "deep_dive",
        "tech_dive",
        "deep_qa",
        "dd_checklist",
        "earnings_review",
        "health_check",
    ).joinToString(",")

    /** Initial load: identify, list notes, fetch the latest body. */
    fun bootstrap() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, errorMessage = null)
            try {
                val (me, loadedNotes) = withContext(Dispatchers.IO) {
                    val identity = client.me()
                    val recent = client.listNotes(days = 14, limit = 30)
                    val deep = client.listNotes(
                        days = 45, limit = 12, kinds = deepResearchKinds,
                    )
                    identity to Pair(recent, deep)
                }
                val notes = loadedNotes.first
                val deepResearch = loadedNotes.second
                val latest = notes.firstOrNull()
                val detail = if (latest != null) {
                    withContext(Dispatchers.IO) { client.fetchNote(latest.researchId) }
                } else null
                _state.value = _state.value.copy(
                    recipient = me.recipient,
                    notes = notes,
                    deepResearch = deepResearch,
                    selected = detail,
                    loading = false,
                    lastRefreshedAt = System.currentTimeMillis(),
                )
            } catch (e: Throwable) {
                _state.value = _state.value.copy(
                    loading = false,
                    errorMessage = friendlyError(e),
                )
            }
        }
        startPolling()
    }

    fun refresh() {
        bootstrap()
    }

    fun pickNote(researchId: Int) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, errorMessage = null)
            try {
                val detail = withContext(Dispatchers.IO) { client.fetchNote(researchId) }
                _state.value = _state.value.copy(
                    selected = detail,
                    loading = false,
                    lastRefreshedAt = System.currentTimeMillis(),
                )
            } catch (e: Throwable) {
                _state.value = _state.value.copy(
                    loading = false,
                    errorMessage = friendlyError(e),
                )
            }
        }
    }

    fun clearUploadStatus() {
        _state.value = _state.value.copy(uploadStatus = null, replyStatus = null)
    }

    /**
     * F18b v2 -- unified ChatGPT-style send: optional text + optional image,
     * sent together as ONE action. If image is provided, the text becomes its
     * caption and the call goes to /channel/api/upload_image. If only text,
     * goes to /channel/api/reply. If neither, no-op.
     *
     * The boss explicitly asked for this UX: "why can't it be like regular
     * ChatGPT chat way -- attach an image and send with message together."
     * Previously we had a separate ImageUploadCard with its own caption +
     * Send button; now there's one textarea + a paperclip + one Send.
     */
    fun sendMessage(
        text: String,
        imageBytes: ByteArray? = null,
        imageFilename: String = "image.jpg",
        imageMime: String = "image/jpeg",
    ) {
        val trimmed = text.trim()
        val hasImage = imageBytes != null && imageBytes.isNotEmpty()
        if (trimmed.isEmpty() && !hasImage) return

        if (hasImage && imageBytes!!.size > 8 * 1024 * 1024) {
            _state.value = _state.value.copy(
                uploadStatus = "图片超过 8MB 限制，请压缩后再试",
                errorMessage = null,
            )
            return
        }

        viewModelScope.launch {
            val latestBefore = _state.value.notes.firstOrNull()?.researchId ?: 0
            _state.value = _state.value.copy(
                sending = !hasImage,
                uploadingImage = hasImage,
                replyStatus = if (hasImage) null else "发送中…",
                uploadStatus = if (hasImage) "上传中…AI 正在识别图片内容…" else null,
                errorMessage = null,
            )
            try {
                if (hasImage) {
                    val result = withContext(Dispatchers.IO) {
                        client.uploadImage(
                            imageBytes = imageBytes!!,
                            filename = imageFilename,
                            mimeType = imageMime,
                            caption = trimmed,
                            noteId = _state.value.selected?.researchId,
                        )
                    }
                    val tickers = result.tickerMentions.joinToString(", ").ifEmpty { "无" }
                    val captionTag = if (trimmed.isEmpty()) "" else " | 含说明"
                    _state.value = _state.value.copy(
                        sending = false,
                        uploadingImage = false,
                        uploadStatus = "已识别 (${result.backend})$captionTag " +
                            "话题: ${result.suspectedTopic.ifEmpty { "—" }} | " +
                            "提及: $tickers | 路由意图: ${result.userIntent}",
                        replyStatus = "已发送，等待回复…",
                    )
                } else {
                    val recordedAt = withContext(Dispatchers.IO) {
                        client.postReply(trimmed, _state.value.selected?.researchId)
                    }
                    _state.value = _state.value.copy(
                        sending = false,
                        replyStatus = "已发送 ($recordedAt)，等待回复…",
                    )
                }
                startBurstPoll(latestBefore)
            } catch (e: Throwable) {
                _state.value = _state.value.copy(
                    sending = false,
                    uploadingImage = false,
                    replyStatus = null,
                    uploadStatus = null,
                    errorMessage = "发送失败: ${friendlyError(e)}",
                )
            }
        }
    }

    /** Backward-compat shim so older callers keep compiling. */
    fun sendReply(text: String) = sendMessage(text)
    fun sendImage(
        imageBytes: ByteArray, filename: String, mimeType: String, caption: String = "",
    ) = sendMessage(caption, imageBytes, filename, mimeType)

    /**
     * Burst-poll every 5 seconds for up to 5 minutes after the boss submits a
     * question. Exits early when a new note arrives (research_id > snapshot) --
     * the F13 reply note has landed. After exit, the normal 5-min poll continues.
     * No polling at all happens outside this window, so battery use stays low.
     */
    private fun startBurstPoll(latestResearchIdBefore: Int) {
        fastPollJob?.cancel()
        fastPollJob = viewModelScope.launch {
            val deadlineMs = System.currentTimeMillis() + 5 * 60 * 1000L
            while (System.currentTimeMillis() < deadlineMs) {
                delay(5 * 1000L)
                try {
                    val notes = withContext(Dispatchers.IO) {
                        client.listNotes(days = 14, limit = 30)
                    }
                    val deepResearch = withContext(Dispatchers.IO) {
                        client.listNotes(days = 45, limit = 12, kinds = deepResearchKinds)
                    }
                    val newest = notes.firstOrNull()
                    if (newest != null && newest.researchId > latestResearchIdBefore) {
                        val detail = withContext(Dispatchers.IO) {
                            client.fetchNote(newest.researchId)
                        }
                        _state.value = _state.value.copy(
                            notes = notes,
                            deepResearch = deepResearch,
                            selected = detail,
                            replyStatus = "已收到回复",
                            lastRefreshedAt = System.currentTimeMillis(),
                        )
                        return@launch
                    }
                    _state.value = _state.value.copy(
                        notes = notes,
                        deepResearch = deepResearch,
                        lastRefreshedAt = System.currentTimeMillis(),
                    )
                } catch (_: Throwable) {
                    // soft failure during burst poll -- next tick retries
                }
            }
            // Timeout -- give up; normal 5-min poll will catch up eventually.
            _state.value = _state.value.copy(replyStatus = "已发送（回复尚未到达，可稍后下拉刷新）")
        }
    }

    private fun startPolling() {
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            while (true) {
                delay(5 * 60 * 1000L)        // refresh every 5 min while app is open
                try {
                    val notes = withContext(Dispatchers.IO) {
                        client.listNotes(days = 14, limit = 30)
                    }
                    val deepResearch = withContext(Dispatchers.IO) {
                        client.listNotes(days = 45, limit = 12, kinds = deepResearchKinds)
                    }
                    val latest = notes.firstOrNull()
                    val current = _state.value
                    val detail = if (latest != null && latest.researchId != current.selected?.researchId) {
                        withContext(Dispatchers.IO) { client.fetchNote(latest.researchId) }
                    } else current.selected
                    _state.value = current.copy(
                        notes = notes,
                        deepResearch = deepResearch,
                        selected = detail,
                        lastRefreshedAt = System.currentTimeMillis(),
                    )
                } catch (_: Throwable) {
                    // soft failure during background poll -- next loop tries again
                }
            }
        }
    }

    private fun friendlyError(e: Throwable): String {
        return when (e) {
            is StockClient.StockClientException -> when (e.statusCode) {
                401 -> "登录令牌无效，请联系管理员重新签发"
                404 -> "服务器找不到这条记录"
                503 -> "服务器繁忙或预算用尽，请稍后再试"
                else -> "服务器错误 (${e.statusCode}): ${e.errorTag}"
            }
            else -> e.message ?: e::class.java.simpleName
        }
    }

    override fun onCleared() {
        pollJob?.cancel()
        fastPollJob?.cancel()
        super.onCleared()
    }
}
