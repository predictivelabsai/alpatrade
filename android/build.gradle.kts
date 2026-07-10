allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    // Register the compileSdk override BEFORE evaluationDependsOn(":app") below,
    // which otherwise forces early evaluation and makes afterEvaluate illegal.
    //
    // Some plugins (e.g. flutter_pcm_sound) hardcode an older compileSdk (33) that
    // is below what their transitive androidx deps require (34+). Force every plugin
    // module up to a modern SDK. Reflection keeps this AGP-version-robust.
    afterEvaluate {
        val androidExt = extensions.findByName("android")
        if (androidExt != null) {
            try {
                val m = androidExt.javaClass.methods.firstOrNull {
                    it.name == "compileSdkVersion" &&
                        it.parameterTypes.size == 1 &&
                        it.parameterTypes[0] == Int::class.javaPrimitiveType
                }
                m?.invoke(androidExt, 36)
            } catch (_: Exception) {
                // leave the plugin's own compileSdk in place if we can't override it
            }
        }
    }

    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
