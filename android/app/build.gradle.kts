plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.chaquopy)
    alias(libs.plugins.kotlin.compose)
}

// 把仓库根目录的 seetouch/ Python 包同步进构建目录，作为 Chaquopy 的源码目录之一。
// PC 端更新 Python 代码后重新构建 APK 即自动同步，seetouch/ 是唯一事实来源。
val syncSeetouchPython = tasks.register<Sync>("syncSeetouchPython") {
    from(rootProject.file("../seetouch")) {
        into("seetouch")
    }
    exclude("**/__pycache__/**")
    into(layout.buildDirectory.dir("seetouch-python-src"))
}

tasks.named("preBuild") {
    dependsOn(syncSeetouchPython)
}

// Chaquopy 的 Python 源码合并任务读取上面 Sync 的产物，需显式声明依赖
tasks.matching { it.name.matches(Regex("merge\\w+PythonSources")) }.configureEach {
    dependsOn(syncSeetouchPython)
}

android {
    namespace = "com.seetouch.app"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.seetouch.app"
        minSdk = 30
        targetSdk = 36
        versionCode = 3
        versionName = "1.2"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // arm64-v8a = 真机；x86_64 = 模拟器
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    buildFeatures {
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            // openai 1.30.0 是最后一个不依赖 jiter(Rust 原生库,Chaquopy 无预编译 wheel)的版本;
            // pydantic 锁 1.x(纯 Python wheel),openai SDK 官方兼容 pydantic v1
            install("openai==1.30.0")
            install("pydantic==1.10.22")
            // httpx 0.28 移除了 proxies 参数,openai 1.30 仍在传
            install("httpx==0.27.2")
            install("pillow")
            install("python-dotenv>=1.0.0")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir(layout.buildDirectory.dir("seetouch-python-src"))
        }
    }
}

dependencies {
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    testImplementation(libs.junit)
    // JVM tests need a real JSONObject rather than android.jar's stub.
    testImplementation("org.json:json:20160810")
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}
