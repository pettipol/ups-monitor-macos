import Foundation
import ApplePowerSource
import UPSModel
import UPSRuntime

@main
private enum UPSProbeCommand {
    static func main() async {
        let arguments = Array(CommandLine.arguments.dropFirst())
        guard arguments.isEmpty || arguments == ["--session"] else {
            writeError("Usage: ups-probe [--session]\n")
            exit(2)
        }

        if arguments == ["--session"] {
            await runSessionProbe()
        } else {
            runOrdinalProbe()
        }
    }

    private static func runOrdinalProbe() {
        let snapshot = ApplePowerSourceReader().snapshot()
        let encoder = makeEncoder()
        do {
            let data = try encoder.encode(snapshot)
            writeJSON(data)
        } catch {
            writeError("Unable to encode power-source snapshot.\n")
            exit(EXIT_FAILURE)
        }
    }

    private static func runSessionProbe() async {
        let sessionRead = await AppleSessionReader().snapshot()
        let snapshots: [MonitorSnapshot]
        do {
            snapshots = try AppleSnapshotRuntimeAdapter.snapshots(from: sessionRead)
            for snapshot in snapshots {
                try snapshot.validate()
            }
        } catch {
            writeError("Unable to read or validate Apple session snapshot.\n")
            exit(EXIT_FAILURE)
        }

        do {
            let data = try makeEncoder().encode(snapshots)
            writeJSON(data)
        } catch {
            writeError("Unable to encode Apple session snapshot.\n")
            exit(EXIT_FAILURE)
        }
    }

    private static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }

    private static func writeJSON(_ data: Data) {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([0x0A]))
    }

    private static func writeError(_ message: String) {
        FileHandle.standardError.write(Data(message.utf8))
    }
}
