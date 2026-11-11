import { Alert, App, Button, Empty, Segmented, Spin } from 'antd';
import { ChevronLeft, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { ObjectActionDialog, type ObjectAction } from '../components/ObjectActionDialog';
import { ObjectCatalogue } from '../components/ObjectCatalogue';
import { ObjectTablePanel } from '../components/ObjectTablePanel';
import { PositionDetails, positionOverrun } from '../components/PositionDetails';
import { BitrixReadStatus } from '../components/BitrixReadStatus';
import { request } from '../lib/api';
import type { ObjectManagement, ObjectSection, Position } from '../types';
import { DailyReportPage } from './DailyReportPage';
import './object.css';

export function ObjectPage({ workspace }: { workspace: WorkspaceView }) {
	const { message } = App.useApp();
	const {
		active,
		project,
		data,
		day,
		session,
		allPositions,
		positions,
		objectSection,
		setPage,
		setObjectForm,
		openObjectSection,
		loadSession,
		refresh,
		changeDay,
		setPreview,
	} = workspace;
	const [management, setManagement] = useState<ObjectManagement | null>(null);
	const [error, setError] = useState('');
	const [action, setAction] = useState<ObjectAction | null>(null);
	const [viewPosition, setViewPosition] = useState<string | null>(null);
	const [loadingAction, setLoadingAction] = useState(false);

	useEffect(() => {
		if (!active || objectSection !== 'catalogue') return;
		const controller = new AbortController();
		setManagement(null);
		setError('');
		request<ObjectManagement>('/object/management', undefined, project, controller.signal)
			.then((result) => {
				if (!controller.signal.aborted) setManagement(result);
			})
			.catch((failure) => {
				if (!controller.signal.aborted) setError((failure as Error).message);
			});
		return () => controller.abort();
	}, [project, !!active, objectSection, data]);

	if (!active) {
		return (
			<section className="object-panel">
				<Empty
					description="Добавьте первый объект, чтобы заполнить отчёт"
					image={Empty.PRESENTED_IMAGE_SIMPLE}
				/>
				<Button type="primary" onClick={() => setObjectForm(true)}>
					Добавить объект
				</Button>
			</section>
		);
	}
	if (data?.project?.id !== project)
		return (
			<div className="empty-panel">
				<Spin />
			</div>
		);

	const withManagement = async (build: (details: ObjectManagement) => ObjectAction) => {
		setLoadingAction(true);
		try {
			setAction(build(await request<ObjectManagement>('/object/management', undefined, project)));
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setLoadingAction(false);
		}
	};
	const deleteObject = () =>
		withManagement((details) => ({
			title: 'Удалить объект?',
			label: 'Удалить навсегда',
			danger: true,
			confirmationName: active.name,
			description: (
				<>
					<b>«{active.name}»</b>
					<p>
						Будут удалены работы ({allPositions.length}), отчёты ({details.reports}) и история
						изменений объекта. Восстановить их в приложении нельзя. Файл в Битрикс24 сохранится.
					</p>
				</>
			),
			run: async () => {
				await request('/object/delete', { name: active.name }, project);
				setPage('objects');
				setPreview(null);
				await loadSession().catch(() => message.warning('Обновите список объектов'));
				message.success('Объект удалён');
			},
		}));
	const detach = () =>
		withManagement((details) => ({
			title: 'Отвязать таблицу?',
			label: 'Отвязать таблицу',
			danger: true,
			description: (
				<>
					<b>
						«{data.config.source_name}» · {active.name}
					</b>
					<p>
						Обновления и автоотправка в Битрикс24 остановятся. Файл, смета и отчёты сохранятся.
						Таблицу можно подключить снова.
					</p>
					{details.pending > 0 && (
						<p>Ожидают отправки: {details.pending} отч. Они останутся в приложении.</p>
					)}
				</>
			),
			run: async () => {
				await request('/object/table/detach', {}, project);
				setPreview(null);
				await refresh(true).catch(() => message.warning('Обновите карточку объекта'));
				message.success('Таблица отвязана');
			},
		}));
	const managePosition = (position: Position) => {
		const used = management?.used_positions.includes(position.id);
		const overrun = positionOverrun(position);
		if (!position.hidden && !overrun && used) return;
		const operation = position.hidden ? 'show' : overrun > 0 ? 'hide' : 'delete';
		const label =
			operation === 'show'
				? 'Вернуть в подбор'
				: operation === 'hide'
					? 'Скрыть из подбора'
					: 'Удалить из сметы';
		setAction({
			title: label + '?',
			label,
			danger: operation === 'delete',
			description: (
				<>
					<b>{position.name}</b>
					<p>
						{operation === 'show'
							? 'Работа снова появится в поиске и новых отчётах.'
							: operation === 'hide'
								? 'У позиции есть перерасход. После подтверждения она исчезнет из поиска и подсказок при заполнении отчёта. Смета и история сохранятся.'
								: 'Позиция будет удалена из сметы приложения. Отменить это действие нельзя. Строка в исходном файле сохранится.'}
					</p>
				</>
			),
			run: async () => {
				await request(
					'/object/positions/' + encodeURIComponent(position.id),
					{ action: operation },
					project,
				);
				await refresh(true).catch(() => message.warning('Обновите карточку объекта'));
				message.success(
					operation === 'show'
						? 'Работа доступна в подборе'
						: operation === 'hide'
							? 'Работа скрыта'
							: 'Работа удалена',
				);
			},
		});
	};
	const openSection = (section: ObjectSection) => {
		if (section !== 'reports' && workspace.textOpen) {
			workspace.audioInput.cancel();
			workspace.setTextOpen(false);
		}
		openObjectSection(section);
	};
	return (
		<div className="object-page">
			<div className="object-page-nav">
				<Button type="text" icon={<ChevronLeft size={17} />} onClick={() => setPage('objects')}>
					Объекты
				</Button>
				<Button
					danger
					type={objectSection === 'reports' ? 'text' : 'default'}
					size={objectSection === 'reports' ? 'small' : 'middle'}
					icon={<Trash2 size={17} />}
					loading={loadingAction}
					aria-label="Удалить объект"
					title="Удалить объект"
					onClick={deleteObject}
				>
					{objectSection === 'reports' ? null : 'Удалить'}
				</Button>
			</div>
			<h1>{active.name}</h1>
			<Segmented<ObjectSection>
				block
				aria-label="Разделы объекта"
				value={objectSection}
				onChange={openSection}
				options={[
					{ label: 'Отчёты', value: 'reports' },
					{ label: 'Смета', value: 'catalogue' },
					{ label: 'Таблица', value: 'table' },
				]}
			/>
			{objectSection === 'reports' && (
				<>
					<BitrixReadStatus workspace={workspace} />
					{!positions.length && !workspace.lines.length ? (
						<section className="object-panel">
							<Alert
								type="info"
								showIcon
								message={allPositions.length ? 'Все работы скрыты' : 'Сначала добавьте смету'}
							/>
							<Button
								type="primary"
								onClick={() => openSection(allPositions.length ? 'catalogue' : 'table')}
							>
								{allPositions.length ? 'Открыть смету' : 'Добавить таблицу'}
							</Button>
						</section>
					) : (
						<DailyReportPage workspace={workspace} />
					)}
				</>
			)}
			{objectSection === 'catalogue' && (
				<ObjectCatalogue
					workspace={workspace}
					management={management}
					error={error}
					onManage={managePosition}
					onView={(position) => setViewPosition(position.id)}
				/>
			)}
			{objectSection === 'table' && (
				<ObjectTablePanel key={data.config.source} workspace={workspace} onDetach={detach} />
			)}
			{objectSection === 'reports' && day !== session.today && (
				<Button onClick={() => void changeDay(session.today)}>
					Вернуться к сегодняшнему отчёту
				</Button>
			)}
			{action && <ObjectActionDialog action={action} close={() => setAction(null)} />}
			{viewPosition && workspace.byId[viewPosition] && (
				<PositionDetails
					key={viewPosition}
					workspace={workspace}
					position={workspace.byId[viewPosition]}
					close={() => setViewPosition(null)}
					manage={managePosition}
				/>
			)}
		</div>
	);
}
