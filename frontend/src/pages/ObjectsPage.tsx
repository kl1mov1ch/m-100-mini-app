import { Button, Empty } from 'antd';
import 'dayjs/locale/ru';
import { Building2, ChevronRight, Plus, Users } from 'lucide-react';
import { AdminOverview } from '../components/AdminOverview';
import { RoleSwitch } from '../components/RoleSwitch';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { QuickReportComposer } from '../components/QuickReportComposer';
import { countLabel, Money } from '../lib/format';
export function ObjectsPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		project,
		setObjectForm,
		setProjectOwner,
		isAdmin,
		selectObject,
		loadUsers,
		projects,
		summaryDate,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<h1>{isAdmin ? 'Все объекты' : 'Объекты'}</h1>
				</div>
				<Button
					type={session.projects.length ? 'default' : 'primary'}
					icon={<Plus size={17} />}
					onClick={() => {
						setProjectOwner(undefined);
						setObjectForm(true);
						if (isAdmin) void loadUsers();
					}}
				>
					Новый объект
				</Button>
			</div>
			{session.can_switch_role && (
				<div className="dashboard-role">
					<RoleSwitch workspace={workspace} />
				</div>
			)}
			{isAdmin && <AdminOverview workspace={workspace} />}
			{!isAdmin && workspace.positions.length > 0 && <QuickReportComposer workspace={workspace} />}
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
								{p.table?.pending_review
									? 'Проверьте импорт'
									: p.table?.read_connected
										? 'Таблица подключена'
										: p.source === 'detached'
											? 'Таблица отвязана'
											: p.positions > 0
												? 'Смета в приложении'
												: 'Добавьте таблицу'}
							</span>
							<ChevronRight size={17} />
						</div>
						<h2>{p.name}</h2>
						<p>
							{isAdmin && p.owner_name + ' · '}
							{countLabel(p.positions, 'работа', 'работы', 'работ')}
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
								{p.pending && p.table?.write_connected
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
					<Empty
						image={Empty.PRESENTED_IMAGE_SIMPLE}
						description={
							session.projects.length
								? 'По выбранным фильтрам объектов нет'
								: 'Создайте первый объект и подключите его смету'
						}
					/>
				</div>
			)}
		</>
	);
}
