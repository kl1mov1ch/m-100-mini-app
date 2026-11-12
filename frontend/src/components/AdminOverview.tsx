import { Select } from 'antd';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { Money } from '../lib/format';
import { DatePicker } from './ResponsiveDatePicker';

export function AdminOverview({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		projects,
		summaryDate,
		changeSummaryDate,
		summaryProject,
		setSummaryProject,
		ownerFilter,
		setOwnerFilter,
	} = workspace;
	const owners = [
		...new Map(session.projects.map((project) => [project.owner_id, project.owner_name])),
	];
	const completed = projects.filter((project) => project.today_confirmed).length;
	const expected = projects.filter((project) => project.positions > 0).length;
	return (
		<section className="admin-overview">
			<div className="admin-overview-filters">
				<label>
					Дата
					<DatePicker
						aria-label="Дата проверки отчётов"
						value={dayjs(summaryDate)}
						format="DD.MM.YYYY"
						allowClear={false}
						workDates={[
							...new Set(session.projects.flatMap((project) => project.work_dates || [])),
						]}
						onChange={(date) => date && void changeSummaryDate(date.format('YYYY-MM-DD'))}
					/>
				</label>
				<label>
					Объект
					<Select
						aria-label="Объект для проверки"
						value={summaryProject}
						onChange={setSummaryProject}
						options={[
							{ value: 'all', label: 'Все объекты' },
							...session.projects
								.filter((project) => ownerFilter === 'all' || project.owner_id === ownerFilter)
								.map((project) => ({ value: project.id, label: project.name })),
						]}
					/>
				</label>
				{owners.length > 1 && (
					<label className="admin-owner-filter">
						Мастер
						<Select
							aria-label="Мастер для проверки"
							value={ownerFilter}
							onChange={(value) => {
								setOwnerFilter(value);
								if (
									value !== 'all' &&
									session.projects.find((project) => project.id === summaryProject)?.owner_id !==
										value
								) {
									setSummaryProject('all');
								}
							}}
							options={[
								{ value: 'all', label: 'Все мастера' },
								...owners.map(([value, label]) => ({ value, label })),
							]}
						/>
					</label>
				)}
			</div>
			<dl
				className="admin-metrics"
				aria-label={'Сводка за ' + dayjs(session.selected_date).format('D MMMM')}
			>
				<div className="admin-metric-money">
					<dt>Выработка за день</dt>
					<dd>
						<Money value={projects.reduce((sum, project) => sum + project.today_amount, 0)} />
					</dd>
				</div>
				<div className={expected && completed < expected ? 'admin-metric-pending' : undefined}>
					<dt>Отчёты</dt>
					<dd>
						{completed} из {expected}
					</dd>
				</div>
				<div>
					<dt>Работы</dt>
					<dd>{projects.reduce((sum, project) => sum + project.today_positions, 0)}</dd>
				</div>
				<div>
					<dt>Работники</dt>
					<dd>{projects.reduce((sum, project) => sum + (project.today_crew || 0), 0)}</dd>
				</div>
			</dl>
		</section>
	);
}
