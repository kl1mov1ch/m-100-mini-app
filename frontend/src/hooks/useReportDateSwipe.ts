import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { useHorizontalSwipe } from './useHorizontalSwipe';

export function useReportDateSwipe(workspace: WorkspaceView) {
	const { day, session, changeDay, report, dirty, busy, isAdmin } = workspace;
	return useHorizontalSwipe((step) => {
		if (!isAdmin && report && dirty) return;
		const next = dayjs(day).add(step, 'day').format('YYYY-MM-DD');
		if (next <= session.today) void changeDay(next);
	}, busy);
}
