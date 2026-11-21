/* Finite synthetic C/Python interoperability fixture: no driver linkage. */
#define main operational_assertion_groups
#include "test_operational_formatter.c"
#undef main

int main(void)
{
    const uint64_t elapsed[] = {0U, 600000U, (uint64_t)UINT32_MAX + 1U,
                               MLINK_OPERATIONAL_MAX_SAFE_INTEGER};
    const uint64_t sequence[] = {1U, 121U, 1U, 1U};
    const mlink_operational_end_reason_t reasons[] = {
        MLINK_OPERATIONAL_END_CANCELLED, MLINK_OPERATIONAL_END_DEVICE_LOST,
        MLINK_OPERATIONAL_END_SESSION_LOST, MLINK_OPERATIONAL_END_GUARD_ERROR,
        MLINK_OPERATIONAL_END_OUTPUT_ERROR
    };
    mlink_operational_field_t fields[MLINK_CONTINUOUS_FIELD_COUNT];
    char line[MLINK_CONTINUOUS_MAX_LINE];
    size_t i;
    assert(operational_assertion_groups() == 0);
    for (i = 0U; i < sizeof(elapsed) / sizeof(elapsed[0]); ++i) {
        make_unavailable(fields);
        set_observed(fields, 0U, "OL", elapsed[i]);
        set_observed(fields, 1U, "90", elapsed[i]);
        set_observed(fields, 4U, "24.0", elapsed[i]);
        mlink_operational_field_mirror(&fields[5], &fields[4]);
        set_observed(fields, 11U, "50", elapsed[i]);
        set_observed(fields, 13U, "200", elapsed[i]);
        set_observed(fields, 15U, "100", elapsed[i]);
        set_observed(fields, 12U, "25", elapsed[i]);
        set_observed(fields, 14U, "400", elapsed[i]);
        set_observed(fields, 16U, "100", elapsed[i]);
        assert(make_sample(line, sizeof(line), sequence[i], elapsed[i], fields));
        assert(fputs(line, stdout) >= 0);
    }
    for (i = 0U; i < sizeof(reasons) / sizeof(reasons[0]); ++i) {
        assert(mlink_operational_end_line(line, sizeof(line),
               MLINK_OPERATIONAL_MAX_SAFE_INTEGER, reasons[i]));
        assert(fputs(line, stdout) >= 0);
    }
    return 0;
}
