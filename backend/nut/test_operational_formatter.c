/* Synthetic serializer tests only; this file contains no driver or transport calls. */
#include "apcmicrolink-continuous.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void make_unavailable(mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT])
{
	mlink_operational_fields_clear(fields);
}

static int make_sample(char *out, size_t out_size, uint64_t sequence,
	uint64_t elapsed_ms,
	const mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT])
{
	uint64_t slot = elapsed_ms / MLINK_OPERATIONAL_SLOT_MS;
	uint64_t missed = sequence <= slot + 1U ? slot + 1U - sequence : 0U;
	return mlink_operational_sample_line(out, out_size, sequence, slot,
		elapsed_ms, missed, fields);
}

static void set_observed(mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT],
	size_t index, const char *value, uint64_t observed_ms)
{
	assert(mlink_operational_field_observed(&fields[index],
		fields[index].kind, value, observed_ms));
}

static void test_duration_and_integer_boundaries(void)
{
	mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
	char line[MLINK_CONTINUOUS_MAX_LINE];
	uint64_t elapsed, slot;
	make_unavailable(fields);
	assert(make_sample(line, sizeof(line), 121U, 600000U, fields));
	assert(strstr(line, "\"protocol\":\"ups-monitor.continuous.v2\"") != NULL);
	assert(strstr(line, "\"schema_version\":2") != NULL);
	assert(strlen(line) <= MLINK_CONTINUOUS_MAX_LINE);
	assert(line[strlen(line) - 1U] == '\n');

	elapsed = UINT32_MAX;
	slot = elapsed / MLINK_OPERATIONAL_SLOT_MS;
	assert(make_sample(line, sizeof(line), 1U, elapsed, fields));
	assert(strstr(line, "\"elapsed_ms\":4294967295") != NULL);

	elapsed = MLINK_OPERATIONAL_MAX_SAFE_INTEGER;
	slot = elapsed / MLINK_OPERATIONAL_SLOT_MS;
	assert(make_sample(line, sizeof(line), 1U, elapsed, fields));
	assert(strstr(line, "\"elapsed_ms\":9007199254740991") != NULL);
	assert(strstr(line, "\"slot\":1801439850948") != NULL);
	assert(slot == 1801439850948U);
}

static void test_invalid_counters_and_output_cap(void)
{
	mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
	struct guarded_line { unsigned char before; char line[64]; unsigned char after; } guarded;
	char line[MLINK_CONTINUOUS_MAX_LINE];
	make_unavailable(fields);
	assert(!mlink_operational_sample_line(line, sizeof(line), 0U, 0U, 0U, 1U, fields));
	assert(!mlink_operational_sample_line(line, sizeof(line), 1U, 0U,
		MLINK_OPERATIONAL_MAX_SAFE_INTEGER + 1U, 0U, fields));
	assert(!mlink_operational_sample_line(line, sizeof(line), UINT64_MAX,
		0U, 0U, 0U, fields));
	assert(!mlink_operational_sample_line(line, sizeof(line), 2U, 0U, 0U, 0U, fields));
	assert(!mlink_operational_sample_line(line, sizeof(line), 1U, 1U, 0U, 1U, fields));

	memset(&guarded, 0xA5, sizeof(guarded));
	assert(!make_sample(guarded.line, sizeof(guarded.line), 1U, 0U, fields));
	assert(guarded.before == 0xA5 && guarded.after == 0xA5);
}

static void test_observation_status_alias_and_dependencies(void)
{
	mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
	char line[MLINK_CONTINUOUS_MAX_LINE];
	make_unavailable(fields);
	set_observed(fields, 0U, "OL", 0U);
	assert(make_sample(line, sizeof(line), 1U, 0U, fields));
	assert(strstr(line, "\"ups.status\":{\"value\":\"OL\",\"observed_ms\":0") != NULL);
	fields[0].observed_ms = 1U;
	assert(!make_sample(line, sizeof(line), 1U, 0U, fields));

	make_unavailable(fields);
	set_observed(fields, 0U, "OL OB", 0U);
	assert(!make_sample(line, sizeof(line), 1U, 0U, fields));

	make_unavailable(fields);
	set_observed(fields, 4U, "24.0", 0U);
	assert(!make_sample(line, sizeof(line), 1U, 0U, fields));

	make_unavailable(fields);
	set_observed(fields, 15U, "204.75", 0U);
	assert(!make_sample(line, sizeof(line), 1U, 0U, fields));

	make_unavailable(fields);
	set_observed(fields, 11U, "50", 0U);
	set_observed(fields, 13U, "200", 0U);
	set_observed(fields, 15U, "100", 0U);
	set_observed(fields, 12U, "25", 0U);
	set_observed(fields, 14U, "400", 0U);
	set_observed(fields, 16U, "100", 0U);
	assert(make_sample(line, sizeof(line), 1U, 0U, fields));
}

static void test_operational_end_reasons(void)
{
	char line[MLINK_CONTINUOUS_MAX_LINE];
	assert(mlink_operational_end_line(line, sizeof(line), 600000U,
		MLINK_OPERATIONAL_END_CANCELLED));
	assert(strstr(line, "\"protocol\":\"ups-monitor.continuous.v2\"") != NULL);
	assert(strstr(line, "\"reason\":\"cancelled\"") != NULL);
	assert(strstr(line, "duration_complete") == NULL);
	assert(!mlink_operational_end_line(line, sizeof(line), 0U,
		(mlink_operational_end_reason_t)99));
	assert(!mlink_operational_end_line(line, sizeof(line),
		MLINK_OPERATIONAL_MAX_SAFE_INTEGER + 1U,
		MLINK_OPERATIONAL_END_DEVICE_LOST));
}

int main(void)
{
	test_duration_and_integer_boundaries();
	test_invalid_counters_and_output_cap();
	test_observation_status_alias_and_dependencies();
	test_operational_end_reasons();
	puts("operational_formatter_only=true status=PASS");
	return 0;
}
