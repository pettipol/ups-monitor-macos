/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic APC Microlink frames for the private full-NUT process-flow fixture. */
#include "test_hidapi_full_frames.h"

#include <string.h>

#include "full_checksum_generated.inc"

static const unsigned char page0_only_frame[15] = {
	0x00, 0x01, 0x0C, 0x01, 0x00, 0x00, 0x00, 0x00,
	0x00, 0x00, 0x00, 0x00, 0x00, 0x57, 0x9A
};

static size_t metrics_frame(int updated, unsigned char frame[31])
{
	static const unsigned char descriptor[12] = {
		0xF8, 0x02, 0xFE, 0x04, 0xFE, 0x05, 0x20, 0x9F,
		0xFF, 0xFF, 0xFF, 0xFF
	};
	unsigned char checksum0, checksum1;
	unsigned int charge = updated ? 76U : 75U;
	unsigned int runtime = updated ? 590U : 600U;

	memset(frame, 0, 31);
	frame[0] = 0x00U;
	frame[1] = 0x01U;
	frame[2] = 28U;
	frame[3] = 1U;
	frame[7] = 0x08U;
	frame[9] = 1U;
	frame[12] = 0x18U;
	memcpy(frame + 13, descriptor, sizeof(descriptor));
	frame[25] = (unsigned char)((charge * 512U) >> 8);
	frame[26] = (unsigned char)(charge * 512U);
	frame[27] = (unsigned char)(runtime >> 8);
	frame[28] = (unsigned char)runtime;
	microlink_checksum(frame, 29, &checksum0, &checksum1);
	frame[29] = checksum0;
	frame[30] = checksum1;
	return 31;
}

size_t fixture_microlink_frame(enum fixture_frame_kind kind, int updated,
	unsigned char *out, size_t capacity)
{
	unsigned char frame[31];
	size_t length;

	if (out == NULL || (updated != 0 && updated != 1)) {
		return 0;
	}

	switch (kind) {
	case FIXTURE_METRICS:
	case FIXTURE_BAD_CHECKSUM:
		length = metrics_frame(updated, frame);
		if (kind == FIXTURE_BAD_CHECKSUM) {
			frame[length - 1] ^= 1U;
		}
		break;
	case FIXTURE_PAGE0_ONLY:
		memcpy(frame, page0_only_frame, sizeof(page0_only_frame));
		length = sizeof(page0_only_frame);
		break;
	default:
		return 0;
	}

	if (capacity < length) {
		return 0;
	}
	memcpy(out, frame, length);
	return length;
}
