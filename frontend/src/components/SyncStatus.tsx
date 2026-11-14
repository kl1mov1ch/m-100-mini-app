import { CheckCheck, Circle, Clock3 } from 'lucide-react';

export function reportStatus(syncStatus?: string | null, hasReport = true, fromBitrix = false) {
	if (!hasReport) return 'missing';
	return syncStatus === 'synced' || (syncStatus === 'imported' && fromBitrix) ? 'sent' : 'pending';
}

const labels = { missing: 'Нет отчёта', pending: 'В приложении', sent: 'В Битрикс24' };
const icons = { missing: Circle, pending: Clock3, sent: CheckCheck };

export function Status({ state }: { state: ReturnType<typeof reportStatus> }) {
	const Icon = icons[state];
	return (
		<span className={'sync-status report-state-' + state}>
			<Icon size={13} aria-hidden />
			<span>{labels[state]}</span>
		</span>
	);
}
