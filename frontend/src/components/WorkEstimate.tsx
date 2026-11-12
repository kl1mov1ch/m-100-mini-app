import { TriangleAlert } from 'lucide-react';
import { estimateBalance, formatWorkVolume } from '../lib/position-volume';
import type { Position } from '../types';
import './work-estimate.css';

type WorkBalance = ReturnType<typeof estimateBalance>;

export function WorkEstimate({ balance, unit }: { balance: WorkBalance; unit: string }) {
	const fields: [string, number][] =
		balance.excess > 0
			? [
					['По смете', balance.planned],
					['Выполнено всего', balance.completed],
					['Перерасход', balance.excess],
				]
			: [
					['По смете', balance.planned],
					['До отчёта', balance.available],
					['За день', balance.today],
					['Остаток после', balance.remaining],
				];
	return (
		<div className="work-estimate">
			<dl className={balance.excess > 0 ? 'work-estimate-excess' : undefined}>
				{fields.map(([label, value]) => (
					<div
						key={label}
						className={label === 'Перерасход' ? 'work-estimate-excess-value' : undefined}
					>
						<dt>{label}</dt>
						<dd>
							{label === 'Перерасход' && '+'}
							{formatWorkVolume(value, unit)}
						</dd>
					</div>
				))}
			</dl>
		</div>
	);
}

export function WorkOverruns({
	items,
	confirmed = false,
}: {
	items: { position: Position; balance: WorkBalance }[];
	confirmed?: boolean;
}) {
	const exceeded = items.filter(({ balance }) => balance.excess > 0);
	if (!exceeded.length) return null;
	return (
		<section className="work-overruns" aria-label="Превышение сметы">
			<strong>
				<TriangleAlert size={17} aria-hidden />
				{confirmed ? 'Подтверждённый перерасход' : 'Превышение сметы'}
			</strong>
			<ul>
				{exceeded.map(({ position, balance }) => (
					<li key={position.id}>
						<span>{position.name}</span>
						<small>
							План {formatWorkVolume(balance.planned, position.unit)} · факт{' '}
							<b>{formatWorkVolume(balance.completed, position.unit)}</b> · перерасход на{' '}
							<b>{formatWorkVolume(balance.excess, position.unit)}</b>
						</small>
					</li>
				))}
			</ul>
		</section>
	);
}
