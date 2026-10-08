import Foundation
import XCTest
@testable import NUTClient

final class ClientBoundaryRegressionTests: XCTestCase {
    func testOptionLikeUPSNamesAreRejectedBeforeLaunchingAProcess() throws {
        for name in ["-D", "-l", "--help"] {
            XCTAssertThrowsError(try UPSCClientConfiguration(
                executableURL: URL(fileURLWithPath: "/usr/bin/true"),
                executableQualification: .completionHardened,
                upsName: name,
                sourceID: "synthetic-boundary"
            )) { error in
                XCTAssertEqual(error as? UPSCClientConfigurationError, .invalidUPSName)
            }
        }
    }

    func testCancellationBeforeRunnerStartsResumesItsContinuation() async {
        let completed = expectation(description: "Pre-cancelled runner finishes")
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            let invocation = UPSCProcessInvocation(
                executableURL: URL(fileURLWithPath: "/usr/bin/true"),
                arguments: [], environment: [:], overallDeadlineSeconds: 0.1,
                maximumStandardOutputBytes: 1024, maximumStandardErrorBytes: 1024
            )
            do {
                _ = try await BoundedProcessRunner(invocation: invocation).run()
                XCTFail("An already-cancelled read must not succeed")
            } catch {
                XCTAssertEqual(error as? UPSCClientError, .cancelled)
            }
            completed.fulfill()
        }
        await fulfillment(of: [completed], timeout: 2)
        task.cancel()
    }
}
