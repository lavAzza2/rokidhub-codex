plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.rokidhub.nexus.plugin.codex"
    compileSdk = 36

    defaultConfig {
        val rokidHubBaseUrl = providers.gradleProperty("rokidHubBaseUrl")
            .orElse("https://rokidhub.com/api/v1/nexus/codex")
            .get()
        applicationId = "com.rokidhub.nexus.plugin.codex"
        minSdk = 30
        targetSdk = 36
        versionCode = 5
        versionName = "0.5.0-beta.1"
        buildConfigField("String", "ROKIDHUB_BASE_URL", "\"$rokidHubBaseUrl\"")
        manifestPlaceholders["usesCleartextTraffic"] = "false"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions { jvmTarget = "11" }
    buildFeatures { buildConfig = true }

    val releaseKeystore = providers.environmentVariable("ROKIDHUB_ANDROID_KEYSTORE").orNull
    val releaseStorePassword = providers.environmentVariable("ROKIDHUB_ANDROID_STORE_PASSWORD").orNull
    val releaseKeyPassword = providers.environmentVariable("ROKIDHUB_ANDROID_KEY_PASSWORD").orNull
    val releaseKeyAlias = providers.environmentVariable("ROKIDHUB_ANDROID_KEY_ALIAS").orElse("rokidhub-codex").get()
    if (releaseKeystore != null && releaseStorePassword != null && releaseKeyPassword != null) {
        signingConfigs {
            create("releaseExternal") {
                storeFile = file(releaseKeystore)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        getByName("debug") {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
        }
        getByName("release") {
            if (signingConfigs.names.contains("releaseExternal")) {
                signingConfig = signingConfigs.getByName("releaseExternal")
            }
        }
    }
}

dependencies {
    implementation("com.github.Anezium.Rokid-Nexus:bus-client:sdk-v0.15.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")
}
