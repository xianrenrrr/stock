package com.stock.research

import android.content.Context
import android.graphics.Color as AndroidColor
import android.net.Uri
import android.os.Bundle
import android.view.ViewGroup
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddPhotoAlternate
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import io.noties.markwon.Markwon
import io.noties.markwon.ext.strikethrough.StrikethroughPlugin
import io.noties.markwon.ext.tables.TablePlugin
import android.graphics.Bitmap
import android.graphics.BitmapFactory

private val AccentOrange = Color(0xFFF0883E)
private val AccentBlue = Color(0xFF58A6FF)
private val Bg = Color(0xFF0E1116)
private val Panel = Color(0xFF161B22)
private val Panel2 = Color(0xFF1F2630)
private val TextDim = Color(0xFF9AA6B2)
private val TextMain = Color(0xFFE6EDF3)
private val Border = Color(0xFF30363D)
private val Good = Color(0xFF3FB950)
private val Bad = Color(0xFFF85149)


class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val client = StockClient(BuildConfig.API_BASE, BuildConfig.API_TOKEN)
        setContent {
            DashboardApp(client = client)
        }
    }
}


private class StockViewModelFactory(private val client: StockClient) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return StockViewModel(client) as T
    }
}


@Composable
private fun DashboardApp(client: StockClient) {
    MaterialTheme(colorScheme = darkColorScheme(
        background = Bg,
        surface = Panel,
        primary = AccentOrange,
        secondary = AccentBlue,
        onBackground = TextMain,
        onSurface = TextMain,
        onPrimary = Color(0xFF1A1107),
    )) {
        Surface(modifier = Modifier.fillMaxSize(), color = Bg) {
            val vm: StockViewModel = viewModel(factory = StockViewModelFactory(client))
            val state by vm.state.collectAsState()
            LaunchedEffect(Unit) { vm.bootstrap() }
            DashboardScreen(
                state = state,
                onRefresh = vm::refresh,
                onPick = vm::pickNote,
                onSendMessage = vm::sendMessage,
                onClearUpload = vm::clearUploadStatus,
            )
        }
    }
}


@Composable
private fun DashboardScreen(
    state: DashboardState,
    onRefresh: () -> Unit,
    onPick: (Int) -> Unit,
    onSendMessage: (String, ByteArray?, String, String) -> Unit,
    onClearUpload: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize().background(Bg)) {
        TopBar(recipient = state.recipient, onRefresh = onRefresh)

        if (state.errorMessage != null) {
            ErrorBanner(state.errorMessage)
        }

        if (state.loading && state.selected == null) {
            Box(
                modifier = Modifier.fillMaxWidth().height(120.dp),
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator(color = AccentOrange)
            }
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            LatestNoteCard(detail = state.selected)
            ChatComposerCard(
                state = state,
                onSendMessage = onSendMessage,
                onClearUpload = onClearUpload,
            )
            HistorySection(notes = state.notes, onPick = onPick)
            FooterDisclaimer()
        }
    }
}


private fun guessFilename(context: Context, uri: Uri, mime: String): String {
    // Try ContentResolver display name first; fall back to a stamped default.
    val cursor = context.contentResolver.query(uri, null, null, null, null)
    cursor?.use { c ->
        val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
        if (idx >= 0 && c.moveToFirst()) {
            val name = c.getString(idx)
            if (!name.isNullOrBlank()) return name
        }
    }
    val ext = when (mime) {
        "image/png" -> "png"
        "image/gif" -> "gif"
        "image/webp" -> "webp"
        else -> "jpg"
    }
    return "image_${System.currentTimeMillis()}.$ext"
}


private fun decodeThumbnail(bytes: ByteArray): Bitmap? {
    // Decode bounds first to compute inSampleSize so we don't load 12MP into RAM.
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    var sample = 1
    while (bounds.outWidth / sample > 240 || bounds.outHeight / sample > 240) {
        sample *= 2
    }
    val opts = BitmapFactory.Options().apply { inSampleSize = sample }
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
}


@Composable
private fun TopBar(recipient: String?, onRefresh: () -> Unit) {
    Surface(color = Panel) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "AI 供应链研报",
                color = TextMain,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = recipient?.let { "你好, $it" } ?: "登录中…",
                    color = TextDim,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.width(8.dp))
                IconButton(onClick = onRefresh) {
                    Icon(Icons.Filled.Refresh, contentDescription = "刷新", tint = TextDim)
                }
            }
        }
    }
}


@Composable
private fun ErrorBanner(message: String) {
    Surface(color = Bad.copy(alpha = 0.18f)) {
        Text(
            text = message,
            color = Bad,
            fontSize = 13.sp,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
        )
    }
}


@Composable
private fun LatestNoteCard(detail: StockClient.NoteDetail?) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Panel),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(18.dp)) {
            if (detail == null) {
                Text(
                    text = "暂无研报。系统会在每天 10:30 / 22:30 北京时间生成。",
                    color = TextDim,
                    fontSize = 14.sp,
                )
                return@Card
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = kindLabel(detail.kind),
                    color = AccentOrange,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                detail.topic?.let {
                    Text("  •  ${cleanTopic(it)}", color = TextDim, fontSize = 12.sp)
                }
                detail.layerFocus?.let { Text("  •  $it", color = TextDim, fontSize = 12.sp) }
                Spacer(Modifier.width(6.dp))
                Text(formatTimestamp(detail.createdAt), color = TextDim, fontSize = 11.sp)
            }
            Spacer(Modifier.height(10.dp))
            MarkdownView(markdown = detail.body)
        }
    }
}


/**
 * F18b v2 -- ChatGPT-style composer.
 *
 * One textarea + paperclip-attach + Send button. Either text alone, image alone,
 * or text+image together. Picked image shows as a thumbnail chip above the
 * textarea with an X to remove it before sending. Send is disabled until at
 * least one of (text, image) is present.
 */
@Composable
private fun ChatComposerCard(
    state: DashboardState,
    onSendMessage: (String, ByteArray?, String, String) -> Unit,
    onClearUpload: () -> Unit,
) {
    val context = LocalContext.current
    var text by remember { mutableStateOf("") }
    var pickedBytes by remember { mutableStateOf<ByteArray?>(null) }
    var pickedFilename by remember { mutableStateOf("image.jpg") }
    var pickedMime by remember { mutableStateOf("image/jpeg") }
    var thumbnail by remember { mutableStateOf<Bitmap?>(null) }

    val pickMedia = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        val resolver = context.contentResolver
        pickedMime = resolver.getType(uri) ?: "image/jpeg"
        pickedFilename = guessFilename(context, uri, pickedMime)
        try {
            val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
            pickedBytes = bytes
            thumbnail = bytes?.let { decodeThumbnail(it) }
            onClearUpload()
        } catch (_: Throwable) {
            pickedBytes = null
            thumbnail = null
        }
    }

    val canSend = !state.sending && !state.uploadingImage &&
                  (text.isNotBlank() || pickedBytes != null)
    val isBusy = state.sending || state.uploadingImage

    Card(
        colors = CardDefaults.cardColors(containerColor = Panel),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "回复 / 给系统的指令 (可附图)",
                color = AccentBlue,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(8.dp))

            // Image preview chip (only when an image is attached)
            if (thumbnail != null) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Panel2, RoundedCornerShape(8.dp))
                        .padding(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Image(
                        bitmap = thumbnail!!.asImageBitmap(),
                        contentDescription = "preview",
                        modifier = Modifier
                            .size(48.dp)
                            .background(Bg, RoundedCornerShape(6.dp)),
                        contentScale = ContentScale.Crop,
                    )
                    Spacer(Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = pickedFilename,
                            color = TextMain, fontSize = 12.sp,
                            maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        Text(
                            text = "${(pickedBytes?.size ?: 0) / 1024} KB · 将与文字一起发送",
                            color = TextDim, fontSize = 10.sp,
                        )
                    }
                    IconButton(
                        onClick = {
                            pickedBytes = null
                            thumbnail = null
                        },
                        enabled = !isBusy,
                    ) {
                        Icon(Icons.Filled.Close, contentDescription = "移除图片", tint = TextDim)
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.fillMaxWidth().heightIn(min = 90.dp),
                placeholder = {
                    Text(
                        if (pickedBytes != null)
                            "(可选) 给图片加一句说明: 例如 '这个走势怎么看' / '深挖一下'"
                        else
                            "例如: 再写短一些 / 多看 A 股 / 帮我深挖 PAM4 DSP",
                        color = TextDim,
                    )
                },
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Panel2,
                    unfocusedContainerColor = Panel2,
                    focusedTextColor = TextMain,
                    unfocusedTextColor = TextMain,
                    cursorColor = AccentOrange,
                    focusedIndicatorColor = AccentBlue,
                    unfocusedIndicatorColor = Border,
                ),
                enabled = !isBusy,
            )

            Spacer(Modifier.height(10.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                // Paperclip / attach button
                IconButton(
                    onClick = {
                        pickMedia.launch(
                            PickVisualMediaRequest(
                                ActivityResultContracts.PickVisualMedia.ImageOnly
                            )
                        )
                    },
                    enabled = !isBusy,
                ) {
                    Icon(
                        Icons.Filled.AttachFile,
                        contentDescription = "附加图片",
                        tint = if (pickedBytes != null) AccentBlue else TextDim,
                    )
                }
                Spacer(Modifier.width(4.dp))

                // Send button
                Button(
                    onClick = {
                        onSendMessage(text, pickedBytes, pickedFilename, pickedMime)
                        // Optimistically clear local composer; ViewModel will
                        // re-set status after the network call.
                        text = ""
                        pickedBytes = null
                        thumbnail = null
                    },
                    enabled = canSend,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    if (isBusy) {
                        CircularProgressIndicator(
                            color = Color(0xFF1A1107),
                            modifier = Modifier.size(14.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Icon(Icons.Filled.Send, contentDescription = null,
                             tint = Color(0xFF1A1107))
                    }
                    Spacer(Modifier.width(6.dp))
                    Text(
                        if (pickedBytes != null) "发送 (含图)" else "发送",
                        color = Color(0xFF1A1107),
                        fontWeight = FontWeight.SemiBold,
                    )
                }

                Spacer(Modifier.width(12.dp))
                // One status line — image-pipeline status takes priority over reply status.
                val status = state.uploadStatus ?: state.replyStatus
                status?.let {
                    Text(it, color = Good, fontSize = 11.sp,
                         maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }

            Spacer(Modifier.height(4.dp))
            Text(
                text = "系统会在下一份研报中根据你的反馈调整。",
                color = TextDim,
                fontSize = 11.sp,
            )
        }
    }
}


@Composable
private fun HistorySection(
    notes: List<StockClient.NoteSummary>,
    onPick: (Int) -> Unit,
) {
    if (notes.isEmpty()) return
    Column {
        Text(
            text = "过去 14 天",
            color = TextDim,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(start = 4.dp, bottom = 8.dp),
        )
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            notes.forEach { note ->
                HistoryItem(note = note, onClick = { onPick(note.researchId) })
            }
        }
    }
}


@Composable
private fun HistoryItem(note: StockClient.NoteSummary, onClick: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Panel),
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
    ) {
        Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = listOfNotNull(
                        kindLabel(note.kind),
                        cleanTopic(note.topic) ?: note.layerFocus,
                    ).joinToString(" • "),
                    color = TextDim,
                    fontSize = 12.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(formatTimestamp(note.createdAt), color = TextDim, fontSize = 11.sp)
            }
            Spacer(Modifier.height(2.dp))
            Text(
                text = cleanPreview(note.bodyPreview),
                color = TextMain,
                fontSize = 13.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}


@Composable
private fun FooterDisclaimer() {
    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            text = "不构成投资建议 / Not financial advice.",
            color = TextDim,
            fontSize = 10.sp,
        )
    }
}


@Composable
private fun MarkdownView(markdown: String) {
    AndroidView(
        modifier = Modifier.fillMaxWidth(),
        factory = { ctx -> buildMarkdownTextView(ctx) },
        update = { tv ->
            val md = Markwon.builder(tv.context)
                .usePlugin(TablePlugin.create(tv.context))
                .usePlugin(StrikethroughPlugin.create())
                .build()
            md.setMarkdown(tv, markdown)
        },
    )
}


private fun buildMarkdownTextView(ctx: Context): TextView {
    return TextView(ctx).apply {
        layoutParams = ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT,
        )
        textSize = 14.5f
        setTextColor(AndroidColor.parseColor("#E6EDF3"))
        setLineSpacing(0f, 1.25f)
    }
}


/**
 * Map a research_reports.kind value to a short Chinese display label.
 * Defaults to "每日" only for the actual daily research push; everything else
 * (replies, discovery theses, grading, health checks, deep dives) gets its
 * own tag so the boss can tell them apart in the history list.
 */
private fun kindLabel(kind: String): String = when (kind) {
    "daily" -> "每日"
    "deep_dive" -> "深挖"
    "discovery_thesis" -> "前瞻"
    "grading" -> "评分"
    "health_check" -> "体检"
    "reply" -> "回复"
    "alert" -> "⚠️ 警报"
    else -> kind
}


/**
 * Strip channel-internal markers from a topic string so the boss sees the
 * caption (or a clean fragment) instead of `[caption]/[image]/[summary]/[topic]`
 * plumbing. Returns null if input was null/blank after cleaning.
 */
private fun cleanTopic(topic: String?): String? {
    if (topic.isNullOrBlank()) return null
    val captionRe = Regex("""\[caption\]\s+(.+?)(?:\s+\[|\s*$)""")
    val captionMatch = captionRe.find(topic)
    if (captionMatch != null) {
        return captionMatch.groupValues[1].trim().take(80)
    }
    // Otherwise: drop any `[xxx]` brackets and collapse whitespace
    val cleaned = topic
        .replace(Regex("""\[[a-z_]+\]"""), " ")
        .replace(Regex("""\s+"""), " ")
        .trim()
    return if (cleaned.isEmpty()) null else cleaned.take(80)
}


/**
 * Same cleanup for body previews. Replaces marker noise with prose.
 */
private fun cleanPreview(body: String?): String {
    if (body.isNullOrBlank()) return ""
    return body
        .replace(Regex("""\[image_pending_local_vision\]\s+\S+"""), "[图片处理中…]")
        .replace(Regex("""\[image\]\s+\S+\.png"""), "[图片]")
        .replace(Regex("""\[caption\]\s+"""), "")
        .replace(Regex("""\[summary\]\s+"""), "")
        .replace(Regex("""\[topic\]\s+"""), "")
        .replace(Regex("""\[ocr\]\s+"""), "")
        .replace(Regex("""\[recipient\]\s+\S+"""), "")
        .replace(Regex("""\[uploaded_at\]\s+\S+"""), "")
        .replace(Regex("""\s+"""), " ")
        .trim()
}


private fun formatTimestamp(iso: String): String {
    if (iso.isBlank()) return "—"
    return runCatching {
        iso.substring(0, minOf(iso.length, 16)).replace('T', ' ')
    }.getOrDefault(iso)
}
