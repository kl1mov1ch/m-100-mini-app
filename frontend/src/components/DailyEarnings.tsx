import { InputNumber } from 'antd';
import { Users } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { countLabel, Money } from '../lib/format';

export function DailyEarnings({ workspace }: { workspace: WorkspaceView }) {
	const {
		amount,
		each,
		extra,
		previewCount,
		crew,
		updateReportCrew,
		parsed,
		parsedIncomplete,
		parsedCrewAmbiguous,
		parsing,
	} = workspace;
	return (
		<section className="daily-earnings" aria-label="Расчёт дневного отчёта">
			<div className="earnings-total" aria-live="polite">
				<span>{parsed.length ? 'Предварительная выработка' : 'Выработка за день'}</span>
				<strong>
					<Money value={amount} />
				</strong>
				<small>{countLabel(previewCount, 'работа', 'работы', 'работ')} за день</small>
			</div>
			<div className="daily-team-summary">
				<div className="earnings-person" aria-live="polite">
					<span>На человека</span>
					<strong>{parsedCrewAmbiguous ? '—' : <Money value={each} />}</strong>
				</div>
				<div className="crew-control">
					<span>
						<Users size={16} /> Бригада
					</span>
					<InputNumber
						aria-label="Количество работников"
						min={1}
						max={1000}
						precision={0}
						value={parsedCrewAmbiguous ? null : crew}
						placeholder={parsedCrewAmbiguous ? '—' : undefined}
						onChange={updateReportCrew}
					/>
				</div>
			</div>
			{(parsing || parsedIncomplete > 0 || parsedCrewAmbiguous) && (
				<div className="earnings-review" role="status">
					{parsing && <span>Подбираем работы…</span>}
					{parsedIncomplete > 0 && <span>Проверьте позиции и объёмы · {parsedIncomplete}</span>}
					{parsedCrewAmbiguous && <span>Уточните численность бригады</span>}
				</div>
			)}
			{extra > 0 && !parsedCrewAmbiguous && (
				<div className="rounding-note">
					{extra} чел. получат по <Money value={each + 0.01} /> для распределения до копейки.
				</div>
			)}
		</section>
	);
}
