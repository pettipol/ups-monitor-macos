/// A reviewed packaging build replaces this nil only in its isolated source copy.
/// No manifest, environment variable or UI input can enable the public default.
enum BundledOperationalReleasePins {
    static let manifestSHA256: String? = nil
}
