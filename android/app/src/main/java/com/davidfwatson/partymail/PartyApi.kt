package com.davidfwatson.partymail

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

class ApiError(message: String, val status: Int = 0) : Exception(message)
class PartyApi(context: Context, val origin: String = BuildConfig.BASE_URL) {
    val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private val secure = SecureStore(context)
    private val cookieKey = "session:$origin"
    private var cookie = secure.read(cookieKey)
    var csrf = ""
        private set
    private val lock = Mutex()
    suspend fun session(): Session = decode<Session>(request("/api/mobile/session")).also { csrf = it.csrf_token }
    suspend fun request(path: String, method: String = "GET", body: JsonObject? = null): JsonObject {
        val bytes = raw(path, method, body?.toString()?.toByteArray(), "application/json")
        return runCatching { json.parseToJsonElement(bytes.decodeToString()).jsonObject }.getOrElse { throw ApiError("The server returned an unexpected response.") }
    }
    inline fun <reified T> decode(value: JsonObject): T = json.decodeFromJsonElement(value)
    suspend fun raw(path: String, method: String = "GET", body: ByteArray? = null, contentType: String? = null): ByteArray = lock.withLock {
        require(path.startsWith('/') && !path.startsWith("//") && !path.contains("..") && !path.contains('#'))
        withContext(Dispatchers.IO) {
            val connection = URL(origin + path).openConnection() as HttpURLConnection
            val watcher = launch(start = CoroutineStart.UNDISPATCHED) { try { awaitCancellation() } finally { connection.disconnect() } }
            try {
                connection.requestMethod = method
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 20_000
                connection.readTimeout = 30_000
                connection.setRequestProperty("Accept", "application/json")
                cookie?.let { connection.setRequestProperty("Cookie", "session=$it") }
                if (method != "GET") connection.setRequestProperty("X-CSRF-Token", csrf)
                if (body != null) {
                    connection.doOutput = true
                    connection.setRequestProperty("Content-Type", contentType ?: "application/json")
                    connection.setFixedLengthStreamingMode(body.size)
                    connection.outputStream.use { it.write(body) }
                }
                val code = connection.responseCode
                connection.headerFields.entries.firstOrNull { it.key?.equals("Set-Cookie", true) == true }?.value?.forEach { line ->
                    val pair = line.substringBefore(';')
                    if (pair.startsWith("session=")) {
                        cookie = pair.substringAfter('=').takeIf { it.isNotEmpty() }
                        if (cookie == null) secure.delete(cookieKey) else if (!secure.save(cookieKey, cookie!!)) throw ApiError("Couldn't save your session securely. Try signing in again.")
                    }
                }
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val bytes = stream?.use { input ->
                    val output = ByteArrayOutputStream(); val buffer = ByteArray(8192)
                    while (true) {
                        coroutineContext.ensureActive()
                        val count = input.read(buffer); if (count < 0) break
                        if (output.size() + count > 20 * 1024 * 1024) throw ApiError("The response is too large.")
                        output.write(buffer, 0, count)
                    }
                    output.toByteArray()
                } ?: ByteArray(0)
                if (code !in 200..299) {
                    val message = runCatching { json.parseToJsonElement(bytes.decodeToString()).jsonObject["error"]?.jsonPrimitive?.content }.getOrNull()
                    throw ApiError(message ?: when(code) { 401 -> "Your session expired. Sign in again."; 403 -> "You don't have access to this action. Refresh and try again."; 404, 410 -> "This invitation expired or is no longer available."; 409 -> "This event changed on another device. Reload it before saving."; 429 -> "Too many requests. Please wait a moment."; else -> "The server couldn't complete this request ($code)." }, code)
                }
                bytes
            } catch (e: CancellationException) { throw e }
            catch (e: ApiError) { throw e }
            catch (_: Exception) { coroutineContext.ensureActive(); throw ApiError("Couldn't reach Party Mail. Check your connection and try again.") }
            finally { watcher.cancel(); connection.disconnect() }
        }
    }
    suspend fun upload(context: Context, slug: String, uri: Uri): String = withContext(Dispatchers.IO) {
        val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream(); val buffer = ByteArray(8192)
            while (true) { val n = input.read(buffer); if (n < 0) break; if (out.size() + n > 8 * 1024 * 1024) throw ApiError("Choose a JPEG, PNG, or WebP image smaller than 8 MB."); out.write(buffer, 0, n) }
            out.toByteArray()
        } ?: throw ApiError("Couldn't read this photo.")
        val mime = context.contentResolver.getType(uri)?.takeIf { it.startsWith("image/") } ?: throw ApiError("Choose an image file.")
        val boundary = "PartyMail${UUID.randomUUID()}"
        val out = ByteArrayOutputStream()
        out.write("--$boundary\r\nContent-Disposition: form-data; name=\"image\"; filename=\"photo\"\r\nContent-Type: $mime\r\n\r\n".toByteArray())
        out.write(bytes); out.write("\r\n--$boundary--\r\n".toByteArray())
        json.parseToJsonElement(raw("/api/mobile/events/$slug/upload", "POST", out.toByteArray(), "multipart/form-data; boundary=$boundary").decodeToString()).jsonObject["url"]!!.jsonPrimitive.content
    }
    fun rememberRSVP(slug: String, token: String) { if (!secure.save("rsvp:$origin:$slug", token)) throw ApiError("Your response was saved, but this device couldn't save the update link. Keep the email confirmation.") }
    fun savedRSVP(slug: String): String? = secure.read("rsvp:$origin:$slug")
    fun clearSession() { cookie = null; csrf = ""; secure.delete(cookieKey) }
}
fun payload(vararg fields: Pair<String, Any?>) = buildJsonObject {
    for ((key, value) in fields) when(value) { is String -> put(key, value); is Boolean -> put(key, value); is Int -> put(key, value); null -> put(key, JsonNull) }
}
fun JsonObject.string(key: String): String = this[key]?.jsonPrimitive?.contentOrNull ?: ""
fun JsonObject.rows(key: String): List<JsonObject> = this[key]?.jsonArray?.map { it.jsonObject } ?: emptyList()
