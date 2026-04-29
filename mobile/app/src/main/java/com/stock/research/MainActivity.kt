package com.stock.research

import android.content.Context
import android.graphics.Color as AndroidColor
import android.os.Bundle
import android.view.ViewGroup
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
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
                onReply = vm::sendReply,
            )
        }
    }
}


@Composable
private fun DashboardScreen(
    state: DashboardState,
    onRefresh: () -> Unit,
    onPick: (Int) -> Unit,
    onReply: (String) -> Unit,
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
            ReplyCard(state = state, onReply = onReply)
            HistorySection(notes = state.notes, onPick = onPick)
            FooterDisclaimer()
        }
    }
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
                    text = if (detail.kind == "deep_dive") "深挖" else "每日",
                    color = AccentOrange,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                detail.topic?.let { Text("  •  $it", color = TextDim, fontSize = 12.sp) }
                detail.layerFocus?.let { Text("  •  $it", color = TextDim, fontSize = 12.sp) }
                Spacer(Modifier.width(6.dp))
                Text(formatTimestamp(detail.createdAt), color = TextDim, fontSize = 11.sp)
            }
            Spacer(Modifier.height(10.dp))
            MarkdownView(markdown = detail.body)
        }
    }
}


@Composable
private fun ReplyCard(state: DashboardState, onReply: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    Card(
        colors = CardDefaults.cardColors(containerColor = Panel),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "回复 / 给系统的指令",
                color = AccentBlue,
                fontSize = 13.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.fillMaxWidth().heightIn(min = 90.dp),
                placeholder = {
                    Text(
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
            )
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = {
                        onReply(text)
                        text = ""
                    },
                    enabled = !state.sending && text.isNotBlank(),
                    colors = ButtonDefaults.buttonColors(containerColor = AccentOrange),
                    shape = RoundedCornerShape(8.dp),
                ) {
                    Icon(Icons.Filled.Send, contentDescription = null, tint = Color(0xFF1A1107))
                    Spacer(Modifier.width(6.dp))
                    Text("发送", color = Color(0xFF1A1107), fontWeight = FontWeight.SemiBold)
                }
                Spacer(Modifier.width(12.dp))
                state.replyStatus?.let { Text(it, color = Good, fontSize = 12.sp) }
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
                        if (note.kind == "deep_dive") "深挖" else "每日",
                        note.topic ?: note.layerFocus,
                    ).joinToString(" • "),
                    color = TextDim,
                    fontSize = 12.sp,
                )
                Text(formatTimestamp(note.createdAt), color = TextDim, fontSize = 11.sp)
            }
            Spacer(Modifier.height(2.dp))
            Text(
                text = note.bodyPreview,
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


private fun formatTimestamp(iso: String): String {
    if (iso.isBlank()) return "—"
    return runCatching {
        iso.substring(0, minOf(iso.length, 16)).replace('T', ' ')
    }.getOrDefault(iso)
}
