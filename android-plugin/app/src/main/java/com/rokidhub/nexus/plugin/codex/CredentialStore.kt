package com.rokidhub.nexus.plugin.codex

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class CredentialStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    val installationId: String
        get() = preferences.getString(INSTALLATION_ID, null) ?: UUID.randomUUID().toString().also {
            preferences.edit().putString(INSTALLATION_ID, it).apply()
        }

    var conversationId: String?
        get() = preferences.getString(CONVERSATION_ID, null)
        set(value) = preferences.edit().apply {
            if (value == null) remove(CONVERSATION_ID) else putString(CONVERSATION_ID, value)
        }.apply()

    var projectName: String?
        get() = preferences.getString(PROJECT_NAME, null)
        set(value) = preferences.edit().apply {
            if (value == null) remove(PROJECT_NAME) else putString(PROJECT_NAME, value)
        }.apply()

    fun readAccessToken(): String? {
        val packed = preferences.getString(ACCESS_TOKEN, null) ?: return null
        return runCatching {
            val encrypted = Base64.decode(packed, Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, encrypted.copyOfRange(0, IV_BYTES)))
            cipher.doFinal(encrypted.copyOfRange(IV_BYTES, encrypted.size)).toString(Charsets.UTF_8)
        }.getOrNull()?.takeIf(String::isNotBlank)
    }

    fun saveAccessToken(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.iv + cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        preferences.edit().putString(ACCESS_TOKEN, Base64.encodeToString(encrypted, Base64.NO_WRAP)).apply()
    }

    fun clearAccessToken() = preferences.edit()
        .remove(ACCESS_TOKEN)
        .remove(CONVERSATION_ID)
        .remove(PROJECT_NAME)
        .apply()

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
            init(
                KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build(),
            )
            generateKey()
        }
    }

    private companion object {
        const val PREFERENCES = "rokidhub_codex_credentials"
        const val INSTALLATION_ID = "installation_id"
        const val ACCESS_TOKEN = "access_token_encrypted"
        const val CONVERSATION_ID = "conversation_id"
        const val PROJECT_NAME = "project_name"
        const val KEY_ALIAS = "rokidhub_nexus_codex_token_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}
