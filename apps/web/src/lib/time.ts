export const DISPLAY_TIME_ZONE = "Asia/Kolkata";
const calendarDate = new Intl.DateTimeFormat("en-CA", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
export const istDateKey = (time: number) => {
  const parts = calendarDate.formatToParts(time);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
};
const date = new Intl.DateTimeFormat("en-GB", {
  timeZone: DISPLAY_TIME_ZONE,
  day: "2-digit",
  month: "short",
  year: "numeric",
});
const clock = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});
export const formatISTDate = (time: number) => date.format(time);
export const formatISTClock = (time: number) => clock.format(time);
export const formatIST = (time: number) =>
  `${formatISTDate(time)}, ${formatISTClock(time)} IST`;
