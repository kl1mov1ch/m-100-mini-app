import { CheckCheck, Circle, Clock3, Wrench } from 'lucide-react';

export function reportStatus(
	syncStatus?: string | null,
	hasReport = true,
	fromBitrix = false,
	hasExtraWork = false,
) {
	if (!hasReport) return hasExtraWork ? 'extra' : 'missing';
	return syncStatus === 'synced' || (syncStatus === 'imported' && fromBitrix) ? 'sent' : 'pending';
}

const labels = {
	missing: 'Нет отчёта',
	pending: 'В приложении',
	sent: 'В Битрикс24',
	extra: 'Доп. работы',
};
const icons = { missing: Circle, pending: Clock3, sent: CheckCheck, extra: Wrench };

export function Status({ state }: { state: ReturnType<typeof reportStatus> }) {
	const Icon = icons[state];
	return (
		<span className={'sync-status report-state-' + state}>
			<Icon size={13} aria-hidden />
			<span>{labels[state]}</span>
		</span>
	);
}
