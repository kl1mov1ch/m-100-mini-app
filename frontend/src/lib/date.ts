import type { ConfigType } from 'dayjs';
import dayjs from 'dayjs';
import 'dayjs/locale/ru';
import timezone from 'dayjs/plugin/timezone';
import utc from 'dayjs/plugin/utc';

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.locale('ru');
dayjs.tz.setDefault('Europe/Minsk');

export default function minskDate(value?: ConfigType) {
	if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value))
		return dayjs.tz(value, 'Europe/Minsk').locale('ru');
	return dayjs(value).tz('Europe/Minsk').locale('ru');
}
