/* SPDX-License-Identifier: GPL-2.0-or-later
 * Fake-only checkpoints. Never installed or active in hardware builds. */
#ifndef REPLAY_OPERATIONAL_HOOKS_H
#define REPLAY_OPERATIONAL_HOOKS_H
#if !defined(MLINK_OPERATIONAL_REPLAY_HOOKS) || !MLINK_OPERATIONAL_REPLAY_HOOKS \
	|| !defined(MLINK_HIDAPI_CONTINUOUS_REPLAY) || !defined(MLINK_HIDAPI_OPERATIONAL_V2)
#error "Operational replay hooks require both fake replay and operational v2"
#endif
#include <stddef.h>
#include <stdio.h>
enum {
	MLINK_REPLAY_PRE_OPEN = 1,
	MLINK_REPLAY_STREAM_ENTER = 2,
	MLINK_REPLAY_PRE_OUTPUT = 3,
	MLINK_REPLAY_FINISHED = 4,
	MLINK_REPLAY_BEFORE_WAIT = 5,
	MLINK_REPLAY_BEFORE_PUBLISHED = 6
};
void mlink_operational_replay_checkpoint(unsigned int checkpoint);
size_t mlink_operational_replay_fwrite(const void *ptr, size_t size,
	size_t count, FILE *stream);
int mlink_operational_replay_fflush(FILE *stream);
#endif
