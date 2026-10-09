package com.davidfwatson.partymail

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Minimal secure storage for the session token — the Keychain.swift analogue.
 * Hand-rolled (androidx.security-crypto is deprecated/abandoned): an AES/GCM
 * key lives in AndroidKeyStore (non-exportable; hardware-backed where the
 * device provides it) and the ciphertext+IV go in plain SharedPreferences.
 * One secret, tiny surface.
 */
class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences("partymail.secure", Context.MODE_PRIVATE)

    fun save(account: String, value: String): Boolean = try {
        val cipher = Cipher.getInstance(TRANSFORM)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val ct = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        // commit(), not apply(): one small credential, and the Boolean should
        // mean it's actually durable (review of #288).
        prefs.edit()
            .putString("$account.iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString("$account.ct", Base64.encodeToString(ct, Base64.NO_WRAP))
            .commit()
    } catch (_: Exception) {
        false
    }

    fun read(account: String): String? = try {
        val iv = prefs.getString("$account.iv", null)?.let { Base64.decode(it, Base64.NO_WRAP) }
        val ct = prefs.getString("$account.ct", null)?.let { Base64.decode(it, Base64.NO_WRAP) }
        if (iv == null || ct == null) null
        else {
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(ct), Charsets.UTF_8)
        }
    } catch (_: Exception) {
        null   // key rotated / corrupted entry → treat as signed out
    }

    fun delete(account: String) {
        prefs.edit().remove("$account.iv").remove("$account.ct").commit()
    }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance(KEYSTORE).apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build())
        return gen.generateKey()
    }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "partymail.securestore"
        const val TRANSFORM = "AES/GCM/NoPadding"
    }
}
