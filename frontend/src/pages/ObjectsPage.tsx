import { Button, Empty, Select } from 'antd';
import 'dayjs/locale/ru';
import { Building2, ChevronRight, Plus, Users } from 'lucide-react';
import { DatePicker } from '../components/ResponsiveDatePicker';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { QuickReportComposer } from '../components/QuickReportComposer';
import { Money } from '../lib/format';
export function ObjectsPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		project,
		setObjectForm,
		setProjectOwner,
		ownerFilter,
		setOwnerFilter,
		positions,
		isAdmin,
		selectObject,
		loadUsers,
		projects,
		summaryDate,
		changeSummaryDate,
		summaryProject,
		setSummaryProject,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{isAdmin ? 'КОНТРОЛЬ ОБЪЕКТОВ' : 'МОИ ОБЪЕКТЫ'}</span>
					<h1>{isAdmin ? 'Все объекты' : 'Объекты'}</h1>
				</div>
				<Button
					type="primary"
					icon={<Plus size={17} />}
					onClick={() => {
						setProjectOwner(undefined);
						setObjectForm(true);
						if (isAdmin) void loadUsers();
					}}
				>
					Добавить
				</Button>
			</div>
			{!isAdmin && <QuickReportComposer workspace={workspace} />}
			<div className={'overview-hero' + (!isAdmin ? ' master-overview' : '')}>
				<div>
					<span>
						{summaryDate === session.today ? 'Выполнено сегодня' : 'Выполнено за выбранный день'}
					</span>
					<strong>
						<Money value={projects.reduce((s, p) => s + p.today_amount, 0)} />
					</strong>
					<small>
						{dayjs(summaryDate).format('D MMMM')} ·{' '}
						{projects.filter((p) => p.today_amount > 0).length} активных объектов
					</small>
				</div>
				<span className="hero-glyph">
					<Building2 size={57} strokeWidth={1} />
				</span>
				<div className="overview-statistics">
					<span>
						<b>{projects.reduce((sum, item) => sum + item.today_positions, 0)}</b>Работ за день
					</span>
					<span>
						<b>{projects.reduce((sum, item) => sum + (item.today_crew || 0), 0)}</b>Работников
					</span>
					<span>
						<b>
							{projects.filter((item) => item.today_confirmed).length} /{' '}
							{projects.filter((item) => item.positions > 0).length}
						</b>
						Отчётов сдано
					</span>
				</div>
			</div>
			{isAdmin && (
				<div className="admin-report-filters">
					<DatePicker
						aria-label="Дата проверки отчётов"
						value={dayjs(summaryDate)}
						format="DD.MM.YYYY"
						allowClear={false}
						workDates={[...new Set(projects.flatMap((project) => project.work_dates || []))]}
						onChange={(date) => date && void changeSummaryDate(date.format('YYYY-MM-DD'))}
					/>
					<Select
						aria-label="Объект для проверки"
						value={summaryProject}
						onChange={setSummaryProject}
						options={[
							{ value: 'all', label: 'Все объекты' },
							...session.projects.map((project) => ({
								value: project.id,
								label: project.name,
							})),
						]}
					/>
				</div>
			)}
			{isAdmin && session.projects.length > 1 && (
				<Select
					className="owner-filter"
					value={ownerFilter}
					onChange={setOwnerFilter}
					options={[
						{ value: 'all', label: 'Все мастера' },
						...[...new Map(session.projects.map((p) => [p.owner_id, p.owner_name])).entries()].map(
							([value, label]) => ({ value, label }),
						),
					]}
				/>
			)}
			<div className="object-grid">
				{projects.map((p) => (
					<button
						className={'object-card ' + (p.id === project ? 'selected' : '')}
						key={p.id}
						onClick={() => selectObject(p.id)}
					>
						<div className="object-card-top">
							<span className="object-tile">
								<Building2 size={21} />
							</span>
							<span className={'connection-dot ' + (p.table?.read_connected ? 'connected' : '')}>
								{p.table?.read_connected
									? 'Таблица подключена'
									: p.table?.pending_review
										? 'Проверьте импорт'
										: 'Добавьте таблицу'}
							</span>
							<ChevronRight size={17} />
						</div>
						<h2>{p.name}</h2>
						<p>
							{p.owner_name} · {p.positions} работ
						</p>
						<div className="object-totals">
							<span>
								{summaryDate === session.today ? 'Сегодня' : dayjs(summaryDate).format('D MMMM')}
								<strong>
									<Money value={p.today_amount} />
								</strong>
							</span>
							<span>
								На человека
								<strong>
									{p.today_crew ? (
										<Money value={p.today_per_person} />
									) : (
										<span className="no-value">—</span>
									)}
								</strong>
							</span>
						</div>
						<div className="object-card-bottom">
							<span>
								<Users size={13} />
								{p.today_crew ? `${p.today_crew} чел.` : 'Бригада не указана'}
							</span>
							<span>
								{p.pending
									? `${p.pending} отч. не отправлено`
									: p.last_change
										? dayjs(p.last_change).format('D MMM, HH:mm')
										: 'Нет новых отчётов'}
							</span>
						</div>
					</button>
				))}
			</div>
			{!projects.length && (
				<div className="empty-panel">
					<Empty description="Добавьте первый объект и загрузите смету" />
					<Button type="primary" onClick={() => setObjectForm(true)}>
						Добавить объект
					</Button>
				</div>
			)}
		</>
	);
}
