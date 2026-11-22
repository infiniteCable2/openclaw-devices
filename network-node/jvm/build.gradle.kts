plugins {
    `java-library`
}

group = "io.openclaw.devices"
version = "1.0.0"

tasks.withType<JavaCompile>().configureEach {
    options.release.set(17)
}

val library = tasks.jar
val contractTests = sourceSets.create("contractTest")

tasks.named<JavaCompile>(contractTests.compileJavaTaskName) {
    classpath = files(library)
}

val contractTest = tasks.register<JavaExec>("contractTest") {
    classpath = contractTests.output + files(library)
    mainClass.set("io.openclaw.devices.network.NetworkDeviceContractTest")
}

tasks.check {
    dependsOn(contractTest)
}
