/* Synthetic regression cases for the continuous candidate helper. */
#include "apcmicrolink-continuous.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void test_numeric_and_status(void)
{
	assert(mlink_continuous_number_valid("0"));
	assert(mlink_continuous_number_valid("-0"));
	assert(mlink_continuous_number_valid("0.5"));
	assert(mlink_continuous_number_valid("-12.5e+2"));
	assert(!mlink_continuous_number_valid(".5"));
	assert(!mlink_continuous_number_valid("1."));
	assert(!mlink_continuous_number_valid("00"));
	assert(!mlink_continuous_number_valid("01.2"));
	assert(!mlink_continuous_number_valid("+1"));
	assert(!mlink_continuous_number_valid("1,0"));
	assert(!mlink_continuous_number_valid("NaN"));
	assert(!mlink_continuous_number_valid("1e999"));
	assert(!mlink_continuous_number_valid("1e"));
	assert(mlink_continuous_status_valid("LB OB"));
	assert(!mlink_continuous_status_valid("OB LB"));
	assert(!mlink_continuous_status_valid("OL OB"));
	assert(!mlink_continuous_status_valid("OB OB"));
	assert(!mlink_continuous_status_valid("CHRG"));
	assert(!mlink_continuous_status_valid("CHRG"));
}

static void test_page_provenance(void)
{
	mlink_continuous_page_t object_pages[3] = {
		{100U, 8U, 1, 1}, {120U, 4U, 1, 1}, {0U, 0U, 0, 0}
	};
	mlink_continuous_page_t blob_pages[3];
	uint64_t oldest = 0;
	memcpy(blob_pages, object_pages, sizeof(blob_pages));
	/* Usage straddles pages: use the older timestamp. */
	assert(mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 6U, 4U, &oldest));
	assert(oldest == 100U);
	/* New object bytes do not advance the already-copied blob's timestamp. */
	object_pages[0].received_ms = 140U;
	assert(mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 6U, 4U, &oldest));
	assert(oldest == 100U);
	/* A rebuilt blob takes the refreshed page timestamp, with its own copy extent. */
	memcpy(blob_pages, object_pages, sizeof(blob_pages));
	assert(mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 6U, 4U, &oldest));
	assert(oldest == 120U);
	/* A zero-filled, never-received page is not an observed zero. */
	assert(!mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 16U, 1U, &oldest));
	/* Short copied page and out-of-range usage fail closed. */
	blob_pages[1].copied_len = 1U;
	assert(!mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 6U, 4U, &oldest));
	assert(!mlink_continuous_page_dependency(blob_pages, 3U, 8U, 24U, 23U, 2U, &oldest));
}

static void test_definition_and_wire(void)
{
	static const unsigned char definition[] = {1U, 2U, 3U, 4U, 0xFFU};
	static const char *const expected_fields[MLINK_CONTINUOUS_FIELD_COUNT] = {
		"ups.status", "battery.charge", "battery.runtime", "battery.voltage",
		"battery.temperature", "ups.temperature", "input.voltage",
		"input.frequency", "output.voltage", "output.current",
		"output.frequency", "ups.load", "experimental.ups.load.apparent",
		"ups.realpower.nominal", "ups.power.nominal", "ups.realpower", "ups.power"
	};
	unsigned char changed[sizeof(definition)];
	mlink_continuous_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
	char line[MLINK_CONTINUOUS_MAX_LINE];
	size_t i;
	assert(mlink_continuous_definition_unchanged(definition, sizeof(definition),
		definition, sizeof(definition), 1U, sizeof(definition)));
	assert(mlink_continuous_definition_range_valid(20U, 19U, 24U, 32U));
	assert(!mlink_continuous_definition_range_valid(20U, 21U, 24U, 32U));
	assert(!mlink_continuous_definition_range_valid(12U, 12U, 24U, 32U));
	assert(!mlink_continuous_definition_range_valid(25U, 20U, 24U, 32U));
	assert(!mlink_continuous_definition_range_valid(50U, 20U, 60U, 32U));
	memcpy(changed, definition, sizeof(definition));
	changed[3]++;
	assert(!mlink_continuous_definition_unchanged(definition, sizeof(definition),
		changed, sizeof(changed), 1U, sizeof(definition)));
	assert(!mlink_continuous_definition_unchanged(definition, sizeof(definition),
		definition, sizeof(definition) - 1U, 1U, sizeof(definition)));
	mlink_continuous_fields_clear(fields);
	assert(fields[13].kind == MLINK_CONTINUOUS_STATIC);
	assert(fields[14].kind == MLINK_CONTINUOUS_STATIC);
	assert(fields[15].kind == MLINK_CONTINUOUS_DRIVER_DERIVED);
	assert(fields[16].kind == MLINK_CONTINUOUS_DRIVER_DERIVED);
	assert(mlink_continuous_field_observed(&fields[0], MLINK_CONTINUOUS_REPORTED,
		"OL", 0U));
	assert(mlink_continuous_field_observed(&fields[1], MLINK_CONTINUOUS_REPORTED,
		"0", 0U));
	assert(mlink_continuous_sample_line(line, sizeof(line), 1U, 0U, 0U, 0U, fields));
	for (i = 0; i < MLINK_CONTINUOUS_FIELD_COUNT; i++) {
		char field_token[80];
		snprintf(field_token, sizeof(field_token), "\"%s\":{", expected_fields[i]);
		assert(strstr(line, field_token) != NULL);
	}
	assert(strstr(line, "\"value\":\"OL\",\"observed_ms\":0") != NULL);
	assert(strstr(line, "\"value\":null,\"observed_ms\":null") != NULL);
	assert(strstr(line, "ups-monitor.continuous.v1") != NULL);
	assert(!mlink_continuous_sample_line(line, sizeof(line), 2U, 0U, 5000U, 0U, fields));
	assert(!mlink_continuous_sample_line(line, sizeof(line), 1U, 23U, 0U, 23U, fields));
	assert(mlink_continuous_sample_line(line, sizeof(line), 2U, 2U, 10000U, 1U, fields));
	for (i = 0; i < sizeof(line) && line[i] != '\0'; i++) { }
	assert(i <= MLINK_CONTINUOUS_MAX_LINE && i != 0U && line[i - 1U] == '\n');
	fields[13].kind = MLINK_CONTINUOUS_REPORTED;
	assert(!mlink_continuous_sample_line(line, sizeof(line), 3U, 2U, 10000U, 0U, fields));
	mlink_continuous_fields_clear(fields);
	assert(mlink_continuous_field_observed(&fields[1], MLINK_CONTINUOUS_REPORTED,
		"1.0\"}\n", 0U));
	assert(!mlink_continuous_sample_line(line, sizeof(line), 1U, 0U, 0U, 0U, fields));
	mlink_continuous_field_unavailable(&fields[4], MLINK_CONTINUOUS_REPORTED);
	mlink_continuous_field_mirror(&fields[5], &fields[4]);
	assert(memcmp(&fields[4], &fields[5], sizeof(fields[4])) == 0);
	mlink_continuous_field_invalid(&fields[4], MLINK_CONTINUOUS_REPORTED);
	mlink_continuous_field_mirror(&fields[5], &fields[4]);
	assert(memcmp(&fields[4], &fields[5], sizeof(fields[4])) == 0);
}

int main(void)
{
	test_numeric_and_status();
	test_page_provenance();
	test_definition_and_wire();
	puts("continuous helpers: named synthetic cases passed");
	return 0;
}
