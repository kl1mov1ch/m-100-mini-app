import { Button, Empty } from 'antd';
import 'dayjs/locale/ru';
import { Building2, Plus } from 'lucide-react';
import { AdminOverview } from '../components/AdminOverview';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { CompactRow } from '../components/CompactRow';
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
			{isAdmin && <AdminOverview workspace={workspace} />}
			{!isAdmin && session.projects.length > 0 && <QuickReportComposer workspace={workspace} />}
			<div className="status-legend">
				<span>
					<i />
					Не отправлен
				</span>
				<span className="sent">
					<i />В Битрикс24
				</span>
			</div>
			<div className="object-grid compact-list">
				{projects.map((p) => (
					<CompactRow
						key={p.id}
						className={'object-card ' + (p.id === project ? 'selected' : '')}
						dialog={false}
						title={p.name}
						leading={<Building2 size={20} />}
						description={
							<>
								{countLabel(p.positions, 'работа', 'работы', 'работ')} ·{' '}
								{p.table?.read_connected
									? 'Подключён'
									: p.source === 'detached'
										? 'Таблица отвязана'
										: p.positions
											? 'Смета в приложении'
											: 'Добавьте таблицу'}
								{isAdmin && ' · ' + p.owner_name}
							</>
						}
						value={<Money value={p.today_amount} />}
						meta={
							<>
								{summaryDate === session.today ? 'Сегодня' : dayjs(summaryDate).format('D MMM')}
								{p.pending
									? ' · ' + p.pending + ' не отправл.'
									: ['synced', 'imported'].includes(p.today_sync_status || '')
										? ' · в Битрикс24'
										: p.today_confirmed
											? ' · в приложении'
											: ' · нет отчёта'}
							</>
						}
						attention={!!p.table?.pending_review || (!!p.pending && !!p.table?.write_connected)}
						status={
							p.pending > 0 || !['synced', 'imported'].includes(p.today_sync_status || '')
								? 'pending'
								: 'sent'
						}
						onClick={() => selectObject(p.id)}
					/>
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
