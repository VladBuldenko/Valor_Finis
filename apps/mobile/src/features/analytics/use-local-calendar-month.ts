import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";

import {
  getLocalCalendarMonth,
  isSameCalendarMonth,
  type CalendarMonth,
} from "./calendar-month";

/**
 * Returns the device's current LOCAL calendar month, re-read every time
 * the screen gains focus (VF-019C).
 *
 * A screen kept in the navigation stack does not re-render by itself
 * when the calendar month changes, so a value computed once at render
 * could stay on the previous month after midnight on the 1st. Re-reading
 * on focus is the minimal fix: returning to the screen after a month
 * boundary moves it to the new month, with no timer or polling. The state
 * only changes when the month actually differs, so focusing within the
 * same month never triggers a re-render or a new query.
 *
 * This is the user's local month, which can briefly differ from the
 * server's date (D13). The backend decides the period's state; a month
 * the server has not reached yet comes back as "future", not as an error.
 */
export function useLocalCalendarMonth(): CalendarMonth {
  const [currentMonth, setCurrentMonth] = useState<CalendarMonth>(() =>
    getLocalCalendarMonth(new Date()),
  );

  useFocusEffect(
    useCallback(() => {
      const focusedMonth = getLocalCalendarMonth(new Date());

      setCurrentMonth((previousMonth) =>
        isSameCalendarMonth(previousMonth, focusedMonth)
          ? previousMonth
          : focusedMonth,
      );
    }, []),
  );

  return currentMonth;
}
