/* SPDX-License-Identifier: GPL-2.0-or-later
 * Synthetic tests of the GPL-covered helper used by guarded NUT sources.
 * Compile with -I pointing at the guarded-source/drivers directory. */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>

#include "nut-guarded-policy.h"

typedef struct {
	uint16_t vid[4], pid[4];
	size_t count, opened_index;
	int read_failure, open_failure, reads, opens, claims, resets;
	double elapsed;
	int clock_failure;
} fake_t;

static int read_id(void *opaque, size_t index, uint16_t *vid, uint16_t *pid)
{
	fake_t *f = opaque;
	f->reads++;
	if ((int)index == f->read_failure)
		return -1;
	*vid = f->vid[index];
	*pid = f->pid[index];
	return 0;
}

static int open_device(void *opaque, size_t index)
{
	fake_t *f = opaque;
	f->opens++;
	f->opened_index = index;
	return f->open_failure ? -1 : 0;
}

static int claim_busy(void *opaque)
{
	fake_t *f = opaque;
	f->claims++;
	return -6;
}

static void reset_device(void *opaque)
{
	((fake_t *)opaque)->resets++;
}

static int elapsed(void *opaque, double *seconds)
{
	fake_t *f = opaque;
	if (f->clock_failure)
		return -1;
	*seconds = f->elapsed;
	return 0;
}

int main(void)
{
	fake_t f = {0};
	size_t selected = 99;
	uint16_t id = 0;
	int i;

	f.read_failure = -1;
	f.count = 3;
	f.vid[0] = 0x1111; f.pid[0] = 0x2222;
	f.vid[1] = 0x051d; f.pid[1] = 0x0003;
	f.vid[2] = 0x3333; f.pid[2] = 0x4444;
	assert(nut_guard_open_unique(f.count, 0x7777, 0x8888,
		read_id, open_device, &f, &selected) == -3);
	assert(f.opens == 0);

	f.vid[2] = 0x051d; f.pid[2] = 0x0003;
	assert(nut_guard_open_unique(f.count, 0x051d, 0x0003,
		read_id, open_device, &f, &selected) == -3);
	assert(f.opens == 0);
	f.vid[2] = 0x3333; f.pid[2] = 0x4444;
	f.read_failure = 2;
	assert(nut_guard_open_unique(f.count, 0x051d, 0x0003,
		read_id, open_device, &f, &selected) == -2);
	assert(f.opens == 0);
	f.read_failure = -1;
	assert(nut_guard_open_unique(f.count, 0x051d, 0x0003,
		read_id, open_device, &f, &selected) == 0);
	assert(f.opens == 1 && f.opened_index == 1 && selected == 1);
	f.open_failure = 1;
	assert(nut_guard_open_unique(f.count, 0x051d, 0x0003,
		read_id, open_device, &f, &selected) == -4);
	assert(f.opens == 2);

	assert(nut_guard_hex_id("051d", &id) && id == 0x051d);
	assert(!nut_guard_hex_id("51d", &id));
	assert(!nut_guard_hex_id("051g", &id));
	assert(nut_guard_claim_once(claim_busy, &f) == -6);
	assert(f.claims == 1);
	nut_guard_maybe_reset(1, reset_device, &f);
	assert(f.resets == 0);
	nut_guard_maybe_reset(0, reset_device, &f);
	assert(f.resets == 1);
	assert(!nut_guard_allows_control(1));
	assert(nut_guard_allows_control(0));
	assert(nut_guard_allows_dump_mode(1, 1, 0, 0, 0));
	assert(nut_guard_allows_dump_mode(2, 1, 0, 0, 0));
	assert(!nut_guard_allows_dump_mode(0, 1, 0, 0, 0));
	assert(!nut_guard_allows_dump_mode(-1, 1, 0, 0, 0));
	assert(!nut_guard_allows_dump_mode(1, 0, 0, 0, 0));
	assert(!nut_guard_allows_dump_mode(1, 2, 0, 0, 0));
	assert(!nut_guard_allows_dump_mode(1, 1, 1, 0, 0));
	assert(!nut_guard_allows_dump_mode(1, 1, 0, 1, 0));
	assert(!nut_guard_allows_dump_mode(1, 1, 0, 0, 1));

	/* Each synthetic frame advances the fake clock; frames cannot renew it. */
	for (i = 0; i < 100; i++) {
		f.elapsed = (double)i / 10.0;
		if (nut_guard_deadline_expired(2.0, elapsed, &f))
			break;
	}
	assert(i == 20);
	f.clock_failure = 1;
	assert(nut_guard_deadline_expired(2.0, elapsed, &f));
	f.clock_failure = 0;
	f.elapsed = -1.0;
	assert(nut_guard_deadline_expired(2.0, elapsed, &f));
	f.elapsed = NAN;
	assert(nut_guard_deadline_expired(2.0, elapsed, &f));
	f.elapsed = INFINITY;
	assert(nut_guard_deadline_expired(2.0, elapsed, &f));
	f.elapsed = 1.0;
	assert(nut_guard_deadline_expired(NAN, elapsed, &f));
	assert(nut_guard_deadline_expired(INFINITY, elapsed, &f));
	puts("guarded policy C stubs: PASS");
	return 0;
}
