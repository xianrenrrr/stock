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
    val selected: StockClient.NoteDetail? = null,
    val loading: Boolean = false,
    val sending: Boolean = false,
    val errorMessage: String? = null,
    val replyStatus: String? = null,
    val lastRefreshedAt: Long = 0L,
)

class StockViewModel(private val client: StockClient) : ViewModel() {

    private val _state = MutableStateFlow(DashboardState())
    val state: StateFlow<DashboardState> = _state.asStateFlow()

    private var pollJob: Job? = null
    private var fastPollJob: Job? = null

    /** Initial load: identify, list notes, fetch the latest body. */
    fun bootstrap() {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true, errorMessage = null)
            try {
                val (me, notes) = withContext(Dispatchers.IO) {
                    val identity = client.me()
                    val recent = client.listNotes(days = 14, limit = 30)
                    identity to recent
                }
                val latest = notes.firstOrNull()
                val detail = if (latest != null) {
                    withContext(Dispatchers.IO) { client.fetchNote(latest.researchId) }
                } else null
                _state.value = _state.value.copy(
                    recipient = me.recipient,
                    notes = notes,
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

    fun sendReply(text: String) {
        if (text.isBlank()) return
        viewModelScope.launch {
            // Snapshot the latest research_id BEFORE submit so the burst-poller
            // can detect the new reply note when it lands.
            val latestBefore = _state.value.notes.firstOrNull()?.researchId ?: 0
            _state.value = _state.value.copy(sending = true, replyStatus = "发送中…", errorMessage = null)
            try {
                val recordedAt = withContext(Dispatchers.IO) {
                    client.postReply(text, _state.value.selected?.researchId)
                }
                _state.value = _state.value.copy(
                    sending = false,
                    replyStatus = "已发送 ($recordedAt)，等待回复…",
                )
                startBurstPoll(latestBefore)
            } catch (e: Throwable) {
                _state.value = _state.value.copy(
                    sending = false,
                    replyStatus = null,
                    errorMessage = "发送失败: ${friendlyError(e)}",
                )
            }
        }
    }

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
                    val newest = notes.firstOrNull()
                    if (newest != null && newest.researchId > latestResearchIdBefore) {
                        val detail = withContext(Dispatchers.IO) {
                            client.fetchNote(newest.researchId)
                        }
                        _state.value = _state.value.copy(
                            notes = notes,
                            selected = detail,
                            replyStatus = "已收到回复",
                            lastRefreshedAt = System.currentTimeMillis(),
                        )
                        return@launch
                    }
                    _state.value = _state.value.copy(
                        notes = notes,
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
                    val latest = notes.firstOrNull()
                    val current = _state.value
                    val detail = if (latest != null && latest.researchId != current.selected?.researchId) {
                        withContext(Dispatchers.IO) { client.fetchNote(latest.researchId) }
                    } else current.selected
                    _state.value = current.copy(
                        notes = notes,
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
