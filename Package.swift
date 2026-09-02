// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Forgis",
    platforms: [
        .macOS("26.0"),
    ],
    products: [
        .executable(name: "ForgisMac", targets: ["ForgisMac"]),
        .executable(name: "forgis-runtime", targets: ["ForgisRuntimeCLI"]),
    ],
    dependencies: [
        .package(path: "../Intatis"),
    ],
    targets: [
        .executableTarget(
            name: "ForgisMac",
            dependencies: [
                .product(name: "IntatisCore", package: "Intatis"),
                .product(name: "IntatisProtocol", package: "Intatis"),
                .product(name: "IntatisProviders", package: "Intatis"),
                .product(name: "IntatisCodexRuntime", package: "Intatis"),
            ],
            path: "Apps/ForgisMac/Sources"
        ),
        .executableTarget(
            name: "ForgisRuntimeCLI",
            dependencies: [
                .product(name: "IntatisCore", package: "Intatis"),
                .product(name: "IntatisProtocol", package: "Intatis"),
                .product(name: "IntatisProviders", package: "Intatis"),
                .product(name: "IntatisCodexRuntime", package: "Intatis"),
            ],
            path: "Apps/ForgisRuntimeCLI/Sources"
        ),
    ]
)
