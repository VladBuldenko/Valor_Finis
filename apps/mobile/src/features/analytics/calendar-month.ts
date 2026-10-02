// Calendar-month arithmetic for the Financial Overview month selector
// (VF-019C). Pure functions on whole calendar numbers only -- no money is
// ever involved here, and no YYYY-MM-DD string is ever turned into a JS
// Date (which could shift the calendar day through a UTC conversion).

// A calendar month; `month` is 1..12, matching the backend's year/month
// query parameters.
export type CalendarMonth = {
  year: number;
  month: number;
};

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// Two-digit month codes as they appear in backend YYYY-MM-DD strings.
const MONTH_CODES = [
  "01",
  "02",
  "03",
  "04",
  "05",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
];

// Returns the device's LOCAL calendar month of a date (getFullYear/
// getMonth, never a UTC accessor).
export function getLocalCalendarMonth(date: Date): CalendarMonth {
  return { year: date.getFullYear(), month: date.getMonth() + 1 };
}

// January -> December of the previous year.
export function previousCalendarMonth({ year, month }: CalendarMonth): CalendarMonth {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 };
}

// December -> January of the next year.
export function nextCalendarMonth({ year, month }: CalendarMonth): CalendarMonth {
  return month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 };
}

// Negative when `first` is earlier than `second`, zero when they are the
// same month, positive when `first` is later.
export function compareCalendarMonths(first: CalendarMonth, second: CalendarMonth): number {
  return first.year !== second.year ? first.year - second.year : first.month - second.month;
}

export function isSameCalendarMonth(first: CalendarMonth, second: CalendarMonth): boolean {
  return compareCalendarMonths(first, second) === 0;
}

// "September 2026".
export function formatCalendarMonthLabel({ year, month }: CalendarMonth): string {
  return `${MONTH_NAMES[month - 1]} ${year}`;
}

// "September 2026" from a backend period_start such as "2026-09-01",
// read straight from the string -- never through new Date(). An
// unexpected value is shown as-is rather than guessed.
export function formatPeriodMonthLabel(periodStart: string): string {
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(periodStart);
  const monthIndex = match ? MONTH_CODES.indexOf(match[2]) : -1;

  return match && monthIndex >= 0
    ? `${MONTH_NAMES[monthIndex]} ${match[1]}`
    : periodStart;
}
