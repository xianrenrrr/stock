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
        versionCode = 2
        versionName = "0.3.0"

        // Strip a trailing "/channel/" or "/" so the user can paste either form
        // (we want just the host root for native API calls).
        val rawBase = (project.findProperty("STOCK_BASE_URL") as? String)?.trim().orEmpty()
            .ifEmpty { "https://stock-research-9aq3.onrender.com" }
        val apiBase = rawBase.removeSuffix("/channel/").removeSuffix("/channel").removeSuffix("/")

        val token = (project.findProperty("STOCK_DEFAULT_TOKEN") as? String)?.trim().orEmpty()

        buildConfigField("String", "API_BASE", "\"$apiBase\"")
        buildConfigField("String", "API_TOKEN", "\"$token\"")
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.10"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
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

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.02.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.8.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.7.0")
    implementation("androidx.appcompat:appcompat:1.6.1")

    // Markdown rendering inside an AndroidView wrapper (Compose-native libs are heavier)
    implementation("io.noties.markwon:core:4.6.2")
    implementation("io.noties.markwon:ext-tables:4.6.2")
    implementation("io.noties.markwon:ext-strikethrough:4.6.2")
}
