import { Segmented } from '../components/Segmented';
import { Alert, App, Empty, Spin } from 'antd';
import { Button } from '../components/Button';
import { SheetModal as Modal } from '../components/SheetModal';
import { NotebookPen } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { ObjectActionDialog, type ObjectAction } from '../components/ObjectActionDialog';
import { ObjectCatalogue } from '../components/ObjectCatalogue';
import { NoteInput } from '../components/NoteInput';
import { ObjectExpenses } from '../components/ObjectExpenses';
import { ObjectTablePanel } from '../components/ObjectTablePanel';
import { PositionDetails } from '../components/PositionDetails';
import { BitrixReadStatus } from '../components/BitrixReadStatus';
import { useHorizontalSwipe } from '../hooks/useHorizontalSwipe';
import { request } from '../lib/api';
import type { CatalogueAction, ObjectManagement, ObjectSection, Position } from '../types';
import { DailyReportPage } from './DailyReportPage';
import './object.css';

const sections: { label: string; value: ObjectSection }[] = [
	{ label: 'Отчёты', value: 'reports' },
	{ label: 'Смета', value: 'catalogue' },
	{ label: 'Доп. работы', value: 'expenses' },
	{ label: 'Таблица', value: 'table' },
];

export function ObjectPage({ workspace }: { workspace: WorkspaceView }) {
	const { message } = App.useApp();
	const {
		active,
		project,
		data,
		allPositions,
		positions,
		objectSection,
		setPage,
		setData,
		setObjectForm,
		openObjectSection,
		loadSession,
		refresh,
		setPreview,
	} = workspace;
	const [action, setAction] = useState<ObjectAction | null>(null);
	const [viewPosition, setViewPosition] = useState<string | null>(null);
	const [loadingAction, setLoadingAction] = useState(false);
	const [objectNote, setObjectNote] = useState<{ previous: string; draft: string }>();
	const [savingNote, setSavingNote] = useState(false);

	const openSection = (section: ObjectSection) => {
		if (section !== 'reports' && workspace.textOpen) {
			workspace.audioInput.cancel();
			workspace.setTextOpen(false);
		}
		openObjectSection(section);
	};
	const sectionSwipe = useHorizontalSwipe(
		(step) => {
			const current = sections.findIndex(({ value }) => value === objectSection);
			const target = sections[current + step];
			if (target) openSection(target.value);
		},
		workspace.busy || !!viewPosition || !!action,
	);

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
	const saveObjectNote = async () => {
		if (!objectNote || savingNote) return;
		setSavingNote(true);
		try {
			const result = await request<{ note: string }>(
				'/object/note',
				{ note: objectNote.draft, previous: objectNote.previous },
				project,
			);
			setData((current) =>
				current?.project?.id === project
					? { ...current, config: { ...current.config, object_note: result.note } }
					: current,
			);
			setObjectNote(undefined);
			message.success('Примечание сохранено');
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setSavingNote(false);
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
	const managePosition = (position: Position, operation: CatalogueAction) => {
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
								: 'Работа исчезнет из сметы приложения и новых отчётов. Выполненные объёмы и дата удаления сохранятся в истории, строка в Битрикс24 останется.'}
					</p>
				</>
			),
			run: async () => {
				await request(
					'/object/positions/' + encodeURIComponent(position.id),
					{ action: operation },
					project,
				);
				if (operation === 'delete') setViewPosition(null);
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
	return (
		<div className="object-page swipe-surface" {...sectionSwipe}>
			<div className="object-heading">
				<h1 title={active.name}>{active.name}</h1>
				<Button
					type="text"
					icon={<NotebookPen size={19} />}
					className="object-note-button"
					data-has-note={!!data.config.object_note}
					aria-label="Примечание к объекту"
					title="Примечание к объекту"
					onClick={() => {
						const previous = data.config.object_note || '';
						setObjectNote({ previous, draft: previous });
					}}
				/>
			</div>
			<Segmented<ObjectSection>
				block
				className="object-section-switch"
				aria-label="Разделы объекта"
				value={objectSection}
				onChange={openSection}
				options={sections}
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
					key={project}
					workspace={workspace}
					onView={(position) => setViewPosition(position.id)}
				/>
			)}
			{objectSection === 'expenses' && (
				<ObjectExpenses
					key={project}
					project={project}
					day={workspace.day}
					onSaved={() =>
						void refresh(true).catch(() => message.warning('Обновите карточку объекта'))
					}
				/>
			)}
			{objectSection === 'table' && (
				<ObjectTablePanel
					key={data.config.source}
					workspace={workspace}
					onDetach={detach}
					onDelete={deleteObject}
					loadingAction={loadingAction}
				/>
			)}
			<Modal
				open={!!objectNote}
				title="Примечание к объекту"
				okText="Применить"
				footer={(_, { OkBtn }) => <OkBtn />}
				confirmLoading={savingNote}
				onOk={() => void saveObjectNote()}
				onCancel={() => !savingNote && setObjectNote(undefined)}
			>
				{objectNote && (
					<NoteInput
						project={project}
						scope="object-note"
						label="Примечание к объекту"
						maxLength={2000}
						value={objectNote.draft}
						onChange={(draft) => setObjectNote((current) => current && { ...current, draft })}
					/>
				)}
			</Modal>
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
