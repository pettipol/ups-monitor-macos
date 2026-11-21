/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef TEST_HIDAPI_FULL_FRAMES_H
#define TEST_HIDAPI_FULL_FRAMES_H

#include <stddef.h>

enum fixture_frame_kind {
	FIXTURE_METRICS = 0,
	FIXTURE_PAGE0_ONLY = 1,
	FIXTURE_BAD_CHECKSUM = 2
};

size_t fixture_microlink_frame(enum fixture_frame_kind kind, int updated,
	unsigned char *out, size_t capacity);

#endif /* TEST_HIDAPI_FULL_FRAMES_H */
