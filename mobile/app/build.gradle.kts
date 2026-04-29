plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.stock.research"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.stock.research"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"

        // Pull URL + optional default token from gradle.properties. CI overrides via -P.
        val baseUrl = (project.findProperty("STOCK_BASE_URL") as? String)
            ?.trim().orEmpty()
            .ifEmpty { "https://stock-research.onrender.com/channel/" }
        val defaultToken = (project.findProperty("STOCK_DEFAULT_TOKEN") as? String)
            ?.trim().orEmpty()

        // Build a final URL: if a token was configured, append ?token= so the dashboard
        // auto-stores it on first open. Otherwise we hit the login screen.
        val finalUrl = if (defaultToken.isNotEmpty()) {
            val sep = if (baseUrl.contains("?")) "&" else "?"
            "$baseUrl${sep}token=$defaultToken"
        } else {
            baseUrl
        }

        buildConfigField("String", "WEBVIEW_URL", "\"$finalUrl\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // Debug keystore signing is fine for a private boss-only install. APK installs
            // via "Unknown sources" on Android; no Play Store, no release keystore needed.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.activity:activity-ktx:1.8.2")
    implementation("androidx.webkit:webkit:1.10.0")
}
