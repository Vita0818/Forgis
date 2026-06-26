// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Forgis",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "ForgisMac", targets: ["ForgisMac"]),
    ],
    targets: [
        .executableTarget(
            name: "ForgisMac",
            path: "Apps/ForgisMac/Sources"
        ),
    ]
)
