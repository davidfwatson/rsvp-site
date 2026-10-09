package com.davidfwatson.partymail

import android.app.Activity
import androidx.credentials.*
import androidx.credentials.exceptions.CreateCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.NoCredentialException
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.*

class Passkeys(private val activity: Activity, private val api: PartyApi) {
    private val manager = CredentialManager.create(activity)
    suspend fun signIn() {
        val options = api.request("/admin/passkey/auth/options", "POST", payload())
        try {
            val result = manager.getCredential(activity, GetCredentialRequest(listOf(GetPublicKeyCredentialOption(options.toString()))))
            val credential = result.credential as? PublicKeyCredential ?: throw ApiError("Unexpected passkey response.")
            api.request("/admin/passkey/auth/verify", "POST", api.json.parseToJsonElement(credential.authenticationResponseJson).jsonObject)
            api.session()
        } catch (e: GetCredentialCancellationException) { throw PasskeyCancelled() }
        catch (_: NoCredentialException) { throw ApiError("No Party Mail passkey is available on this device. Use owner recovery or ask the owner for a one-use sign-in link.") }
        catch (e: CancellationException) { throw e }
        catch (e: ApiError) { throw e }
        catch (_: Exception) { throw ApiError("Couldn't use your passkey. Make sure the installed app certificate is authorized by Party Mail, then try again.") }
    }
    suspend fun register(name: String, invite: String? = null) {
        val route = if (invite == null) "/admin/passkey/register" else "/admin/invite/$invite/register"
        val options = api.request("$route/options", "POST", payload("name" to name))
        try {
            val result = manager.createCredential(activity, CreatePublicKeyCredentialRequest(options.toString())) as? CreatePublicKeyCredentialResponse ?: throw ApiError("Unexpected passkey response.")
            val response = api.json.parseToJsonElement(result.registrationResponseJson).jsonObject.toMutableMap()
            response["name"] = JsonPrimitive(name)
            api.request("$route/verify", "POST", JsonObject(response))
            api.session()
        } catch (e: CreateCredentialCancellationException) { throw PasskeyCancelled() }
        catch (e: CancellationException) { throw e }
        catch (e: ApiError) { throw e }
        catch (_: Exception) { throw ApiError("Couldn't create your passkey. Check this app's certificate authorization and try again.") }
    }
}
class PasskeyCancelled : Exception()
