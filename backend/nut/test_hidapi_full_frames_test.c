/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Raw-byte assertions only; this is not a NUT decoder test. */
#include "test_hidapi_full_frames.h"

#include <stdio.h>
#include <string.h>

#include "full_checksum_generated.inc"

static int failures;

static void check(int condition, const char *name)
{
	if (!condition) {
		fprintf(stderr, "FAIL %s\n", name);
		failures++;
	}
}

static int checksum_ok(const unsigned char *frame, size_t length)
{
	unsigned char check0, check1;
	if (frame == NULL || length < 3) return 0;
	microlink_checksum(frame, length - 2, &check0, &check1);
	return check0 == frame[length - 2] && check1 == frame[length - 1];
}

static void test_legacy_golden(void)
{
	static const unsigned char golden[15] = {
		0x00, 0x01, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x00,
		0x00, 0x00, 0x00, 0x00, 0x00, 0x57, 0x9A
	};
	unsigned char output[32];
	size_t length = fixture_microlink_frame(FIXTURE_PAGE0_ONLY, 0, output, sizeof(output));
	check(length == sizeof(golden), "legacy frame length 15");
	check(memcmp(output, golden, sizeof(golden)) == 0, "legacy frame golden bytes");
	check(checksum_ok(output, length), "legacy frame checksum");
	check(fixture_microlink_frame(FIXTURE_PAGE0_ONLY, 1, output, sizeof(output)) == length
		&& memcmp(output, golden, sizeof(golden)) == 0,
		"page0-only ignores valid update selector");
}

static void test_metrics(int updated)
{
	unsigned char frame[32];
	size_t length = fixture_microlink_frame(FIXTURE_METRICS, updated, frame, sizeof(frame));
	unsigned int expected_charge = updated ? 76U : 75U;
	unsigned int expected_runtime = updated ? 590U : 600U;
	check(length == 31, "metrics frame length 31");
	check(frame[0] == 0x00 && frame[1] == 1 && frame[2] == 28 && frame[3] == 1,
		"metrics object id and page0 geometry");
	check(frame[7] == 0x08 && frame[9] == 1 && frame[11] == 0 && frame[12] == 0x18,
		"metrics page0 flags/version/descriptor pointer");
	check(memcmp(frame + 13, (const unsigned char[]){
		0xF8, 0x02, 0xFE, 0x04, 0xFE, 0x05, 0x20, 0x9F,
		0xFF, 0xFF, 0xFF, 0xFF
	}, 12) == 0, "descriptor grammar literal");
	check(frame[25] == (unsigned char)((expected_charge * 512U) >> 8)
		&& frame[26] == (unsigned char)(expected_charge * 512U),
		"charge raw fixed-point bytes");
	check(frame[27] == (unsigned char)(expected_runtime >> 8)
		&& frame[28] == (unsigned char)expected_runtime,
		"runtime raw fixed-point bytes");
	check(checksum_ok(frame, length), "metrics NUT checksum helper");
}

static void test_bad_checksum(void)
{
	unsigned char good[31], bad[31];
	size_t good_length = fixture_microlink_frame(FIXTURE_METRICS, 0, good, sizeof(good));
	size_t bad_length = fixture_microlink_frame(FIXTURE_BAD_CHECKSUM, 0, bad, sizeof(bad));
	check(good_length == 31 && bad_length == good_length, "bad checksum frame length");
	check(memcmp(good, bad, good_length - 1) == 0, "bad checksum changes only final byte");
	check(bad[bad_length - 1] == (unsigned char)(good[good_length - 1] ^ 1U),
		"bad checksum final-byte xor");
	check(checksum_ok(good, good_length) && !checksum_ok(bad, bad_length),
		"bad checksum rejected by exact NUT helper");
}

static void test_errors_and_bounds(void)
{
	unsigned char output[32], original[32];
	memset(output, 0xA5, sizeof(output));
	memcpy(original, output, sizeof(output));
	check(fixture_microlink_frame(FIXTURE_METRICS, 0, output, 30) == 0,
		"metrics short capacity rejected");
	check(memcmp(output, original, sizeof(output)) == 0, "short capacity leaves output unchanged");
	check(fixture_microlink_frame(FIXTURE_PAGE0_ONLY, 0, output, 14) == 0,
		"legacy short capacity rejected");
	check(fixture_microlink_frame(FIXTURE_METRICS, 0, NULL, sizeof(output)) == 0,
		"null output rejected");
	check(fixture_microlink_frame((enum fixture_frame_kind)-1, 0, output, sizeof(output)) == 0,
		"negative kind rejected");
	check(fixture_microlink_frame((enum fixture_frame_kind)3, 0, output, sizeof(output)) == 0,
		"unknown kind rejected");
	check(fixture_microlink_frame(FIXTURE_METRICS, -1, output, sizeof(output)) == 0,
		"negative update rejected");
	check(fixture_microlink_frame(FIXTURE_METRICS, 2, output, sizeof(output)) == 0,
		"update above one rejected");
	check(memcmp(output, original, sizeof(output)) == 0, "invalid inputs leave output unchanged");
}

int main(void)
{
	test_legacy_golden();
	test_metrics(0);
	test_metrics(1);
	test_bad_checksum();
	test_errors_and_bounds();
	if (failures != 0) return 1;
	puts("PASS synthetic frame bytes; no decoder or device qualification");
	return 0;
}
