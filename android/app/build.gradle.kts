import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.davidfwatson.partymail"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.davidfwatson.partymail"
        minSdk = 28
        targetSdk = 36
        val raw = (project.findProperty("appVersionCode") as String?)?.trim() ?: "1"
        val code = if (raw.matches(Regex("[0-9]+"))) raw.toLongOrNull() else null
        require(code != null && code in 1..2_100_000_000) { "appVersionCode must contain digits only, 1..2100000000; place comments on their own lines." }
        versionCode = code.toInt()
        versionName = (project.findProperty("appVersionName") as String?)?.trim() ?: "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    val uploadStore = System.getenv("PARTYMAIL_UPLOAD_KEYSTORE")
    if (uploadStore != null) {
        signingConfigs.create("upload") {
            storeFile = file(uploadStore)
            storePassword = System.getenv("PARTYMAIL_UPLOAD_PASSWORD")
            keyAlias = System.getenv("PARTYMAIL_UPLOAD_ALIAS") ?: "upload"
            keyPassword = System.getenv("PARTYMAIL_UPLOAD_PASSWORD")
        }
    }
    buildTypes {
        debug {
            val base = (project.findProperty("partyMailBaseUrl") as String?) ?: "https://partymail.app"
            require(base.matches(Regex("https?://[^\\s\\\"\\\\]+"))) { "partyMailBaseUrl must be an HTTP(S) origin." }
            buildConfigField("String", "BASE_URL", "\"${base.trimEnd('/')}\"")
        }
        release {
            isMinifyEnabled = false
            buildConfigField("String", "BASE_URL", "\"https://partymail.app\"")
            if (uploadStore != null) signingConfig = signingConfigs.getByName("upload")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures { compose = true; buildConfig = true }
}
kotlin { compilerOptions { jvmTarget.set(JvmTarget.JVM_17) } }
dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.credentials)
    implementation(libs.androidx.credentials.play.services)
    testImplementation(libs.junit)
}
