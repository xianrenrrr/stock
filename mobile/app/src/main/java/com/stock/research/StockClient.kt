package com.stock.research

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.DataOutputStream
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

/**
 * Thin HTTP client for the /channel/api endpoints. No external HTTP lib --
 * HttpURLConnection + org.json keeps the APK small and avoids OkHttp version conflicts.
 *
 * All calls block; callers must run them off the main thread (we use coroutines
 * with Dispatchers.IO in the ViewModel).
 */
class StockClient(
    private val baseUrl: String,
    private val token: String,
) {

    companion object {
        private const val TAG = "StockClient"
        private const val CONNECT_TIMEOUT_MS = 60_000        // first call may wake a sleeping Render free instance
        private const val READ_TIMEOUT_MS = 60_000
    }

    data class Identity(val recipient: String, val lastSeenAt: String?)

    data class NoteSummary(
        val researchId: Int,
        val kind: String,
        val topic: String?,
        val layerFocus: String?,
        val bodyPreview: String,
        val createdAt: String,
    )

    data class NoteDetail(
        val researchId: Int,
        val kind: String,
        val topic: String?,
        val layerFocus: String?,
        val body: String,
        val createdAt: String,
    )

    class StockClientException(
        val statusCode: Int,
        val errorTag: String,
        message: String,
    ) : RuntimeException(message)

    fun me(): Identity {
        val obj = jsonGet("/channel/api/me")
        return Identity(
            recipient = obj.optString("recipient", ""),
            lastSeenAt = obj.optString("last_seen_at").ifEmpty { null },
        )
    }

    fun listNotes(days: Int = 14, limit: Int = 50, kinds: String? = null): List<NoteSummary> {
        val kindParam = kinds?.takeIf { it.isNotBlank() }?.let { "&kinds=$it" }.orEmpty()
        val obj = jsonGet("/channel/api/notes?days=$days&limit=$limit$kindParam")
        val arr = obj.optJSONArray("notes") ?: JSONArray()
        return (0 until arr.length()).map { i ->
            val n = arr.getJSONObject(i)
            NoteSummary(
                researchId = n.getInt("research_id"),
                kind = n.optString("kind", "daily"),
                topic = n.optString("topic").ifEmpty { null },
                layerFocus = n.optString("layer_focus").ifEmpty { null },
                bodyPreview = n.optString("body_preview", ""),
                createdAt = n.optString("created_at", ""),
            )
        }
    }

    fun fetchNote(researchId: Int): NoteDetail {
        val obj = jsonGet("/channel/api/notes/$researchId")
        return NoteDetail(
            researchId = obj.getInt("research_id"),
            kind = obj.optString("kind", "daily"),
            topic = obj.optString("topic").ifEmpty { null },
            layerFocus = obj.optString("layer_focus").ifEmpty { null },
            body = obj.optString("body", ""),
            createdAt = obj.optString("created_at", ""),
        )
    }

    fun postReply(text: String, noteId: Int? = null): String {
        val body = JSONObject().apply {
            put("text", text)
            if (noteId != null) put("note_id", noteId)
        }
        val resp = jsonPost("/channel/api/reply", body)
        return resp.optString("recorded_at", "")
    }

    /**
     * F18b: upload an image as multipart/form-data to /channel/api/upload_image.
     *
     * imageBytes is the raw file contents (already loaded into memory by the
     * caller -- typically via ContentResolver.openInputStream on a Uri picked
     * via the Photo Picker). filename + mimeType drive the server-side
     * extension allowlist (.png/.jpg/.jpeg/.gif/.webp), 8MB cap is enforced
     * server-side; the caller should sanity-check before this call too.
     *
     * Returns the parsed response JSON: {ok, recorded_at, filename, backend,
     * description, suspected_topic, ticker_mentions[], user_intent}.
     */
    data class ImageUploadResult(
        val recordedAt: String,
        val filename: String,
        val backend: String,
        val description: String,
        val suspectedTopic: String,
        val tickerMentions: List<String>,
        val userIntent: String,
    )

    fun uploadImage(
        imageBytes: ByteArray,
        filename: String,
        mimeType: String,
        caption: String = "",
        noteId: Int? = null,
    ): ImageUploadResult {
        val boundary = "----StockResearch${System.currentTimeMillis()}"
        val conn = openConnection("/channel/api/upload_image", "POST")
        conn.doOutput = true
        // Set fixed-length streaming when we know the body size so the WebView
        // / Render proxy doesn't buffer the whole thing in memory twice.
        conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")

        val out = DataOutputStream(conn.outputStream)

        // Image part
        out.writeBytes("--$boundary\r\n")
        out.writeBytes(
            "Content-Disposition: form-data; name=\"image\"; filename=\"$filename\"\r\n"
        )
        out.writeBytes("Content-Type: $mimeType\r\n\r\n")
        out.write(imageBytes)
        out.writeBytes("\r\n")

        // Optional caption part
        if (caption.isNotEmpty()) {
            out.writeBytes("--$boundary\r\n")
            out.writeBytes("Content-Disposition: form-data; name=\"caption\"\r\n\r\n")
            out.write(caption.toByteArray(StandardCharsets.UTF_8))
            out.writeBytes("\r\n")
        }

        // Optional note_id link
        if (noteId != null) {
            out.writeBytes("--$boundary\r\n")
            out.writeBytes("Content-Disposition: form-data; name=\"note_id\"\r\n\r\n")
            out.writeBytes(noteId.toString())
            out.writeBytes("\r\n")
        }

        out.writeBytes("--$boundary--\r\n")
        out.flush()
        out.close()

        val resp = readJson(conn, "/channel/api/upload_image")
        val mentionsArr = resp.optJSONArray("ticker_mentions") ?: JSONArray()
        val mentions = (0 until mentionsArr.length()).map { mentionsArr.getString(it) }
        return ImageUploadResult(
            recordedAt = resp.optString("recorded_at", ""),
            filename = resp.optString("filename", filename),
            backend = resp.optString("backend", "unknown"),
            description = resp.optString("description", ""),
            suspectedTopic = resp.optString("suspected_topic", ""),
            tickerMentions = mentions,
            userIntent = resp.optString("user_intent", "unknown"),
        )
    }

    private fun openConnection(path: String, method: String): HttpURLConnection {
        val url = URL(baseUrl.trimEnd('/') + path)
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = CONNECT_TIMEOUT_MS
        conn.readTimeout = READ_TIMEOUT_MS
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Accept", "application/json")
        return conn
    }

    private fun jsonGet(path: String): JSONObject {
        val conn = openConnection(path, "GET")
        return readJson(conn, path)
    }

    private fun jsonPost(path: String, body: JSONObject): JSONObject {
        val conn = openConnection(path, "POST")
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        OutputStreamWriter(conn.outputStream, StandardCharsets.UTF_8).use {
            it.write(body.toString())
        }
        return readJson(conn, path)
    }

    private fun readJson(conn: HttpURLConnection, path: String): JSONObject {
        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val raw = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
        Log.d(TAG, "$path -> $code ${raw.take(120)}")
        if (code !in 200..299) {
            val errorTag = try {
                JSONObject(raw).optString("error", "http_$code")
            } catch (_: Throwable) {
                "http_$code"
            }
            throw StockClientException(code, errorTag, "HTTP $code on $path: ${raw.take(200)}")
        }
        return if (raw.isBlank()) JSONObject() else JSONObject(raw)
    }
}
