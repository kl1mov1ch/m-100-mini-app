import { Alert, Button, Empty, InputNumber, Spin, Tag } from 'antd';
import 'dayjs/locale/ru';
import { Check, Mic, Plus, RotateCcw, TextCursorInput, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { DatePicker } from '../components/ResponsiveDatePicker';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { useConfirmWorkRemoval } from '../hooks/useConfirmWorkRemoval';
import { useReportDateSwipe } from '../hooks/useReportDateSwipe';
import { reportStatus, Status } from '../components/SyncStatus';
import { Money, countLabel, nf, shortName, unit } from '../lib/format';
import { DailyEarnings } from '../components/DailyEarnings';
import { AdminDailyReport } from '../components/AdminDailyReport';
import { QuickReportComposer } from '../components/QuickReportComposer';
import { ReportDraftFields } from '../components/ReportDraftFields';
import { WorkEstimate, WorkOverruns } from '../components/WorkEstimate';
import { CompactWorkEditor } from '../components/CompactRow';
import { ReportNoteButton } from '../components/ReportNoteButton';
import { estimateBalance } from '../lib/position-volume';
export function DailyReportPage({ workspace }: { workspace: WorkspaceView }) {
	if (workspace.isAdmin) return <AdminDailyReport workspace={workspace} />;
	return <MasterDailyReport workspace={workspace} />;
}

function MasterDailyReport({ workspace }: { workspace: WorkspaceView }) {
	const [textVisible, setTextVisible] = useState(false);
	const confirmRemoval = useConfirmWorkRemoval();
	const dateSwipe = useReportDateSwipe(workspace);
	const {
		session,
		data,
		busy,
		day,
		project,
		dayNote,
		setDayNote,
		report,
		lines,
		setLines,
		setWorkPicker,
		setReplaceIndex,
		setTextOpen,
		active,
		positions,
		byId,
		changeDay,
		patchLine,
		amount,
		parsed,
		parsedIncomplete,
		parsedCrewAmbiguous,
		parsing,
		confirmParsedReport,
		oldLines,
		estimateLines,
		nextLines,
		deltaIds,
		dirty,
		valid,
		confirm,
		retry,
		openObjectSection,
		restoreDay,
	} = workspace;
	const workBalances = Object.entries(nextLines).flatMap(([id, quantity]) => {
		const position = byId[id];
		return position
			? [{ position, balance: estimateBalance(position, estimateLines[id], quantity) }]
			: [];
	});
	const balances = Object.fromEntries(
		workBalances.map(({ position, balance }) => [position.id, balance]),
	);
	return !data ? (
		<div className="empty-panel">
			{active ? <Spin /> : <Empty description="Сначала добавьте объект" />}
		</div>
	) : (
		<>
			<div className="page-title swipe-surface" {...dateSwipe}>
				<div>
					<h2>Дневной отчёт</h2>
					<Status
						state={reportStatus(
							report?.sync_status,
							Boolean(report?.lines.length),
							data.config.source === 'bitrix',
						)}
					/>
				</div>
				<div className="report-date-actions">
					<ReportNoteButton
						userId={session.user.telegram_id}
						key={day}
						project={project}
						scope={`day-note:${day}`}
						value={dayNote}
						onChange={setDayNote}
						label="Примечание к объекту за день"
						maxLength={2000}
					/>
					<DatePicker
						aria-label="Дата отчёта"
						value={dayjs(day)}
						allowClear={false}
						workDates={data.history.map((report) => report.date)}
						format="DD.MM"
						disabledDate={(d) => d.format('YYYY-MM-DD') > session.today}
						onChange={(d) => d && void changeDay(d.format('YYYY-MM-DD'))}
					/>
				</div>
			</div>
			<DailyEarnings workspace={workspace} />
			<div className="report-toolbar">
				<Button
					type="primary"
					size="small"
					icon={<Plus size={18} />}
					onClick={() => {
						setReplaceIndex(null);
						setWorkPicker(true);
					}}
					disabled={!positions.length}
				>
					Добавить работу
				</Button>
				<Button
					size="small"
					icon={<TextCursorInput size={17} />}
					aria-expanded={textVisible}
					onClick={() => setTextVisible((visible) => !visible)}
					disabled={!positions.length}
				>
					Текст
				</Button>
				<Button
					size="small"
					icon={<Mic size={17} />}
					onClick={() => setTextOpen(true)}
					disabled={!positions.length}
				>
					Голос
				</Button>
			</div>
			{textVisible && <QuickReportComposer workspace={workspace} inline />}
			<ReportDraftFields workspace={workspace} showSubmit={false} />
			<WorkOverruns items={workBalances} confirmed={!!report?.revision && !dirty} />
			<div className="work-list compact-list">
				{lines.map((l, i) => {
					const p = l.item_id ? byId[l.item_id] : null;
					const changed = p && oldLines[p.id] !== l.quantity;
					const balance = p ? balances[p.id] : null;
					return (
						<CompactWorkEditor
							key={l.item_id || l.raw || i}
							title={p?.name || l.raw || 'Выберите работу'}
							description={
								<>
									{nf.format(l.quantity || 0)} {unit(p?.unit || 'ед.')} за день
									{p
										? ' · смета ' + nf.format(p.planned) + ' ' + unit(p.unit)
										: ' · выберите позицию'}
									{l.note?.trim() ? ' · с примечанием' : ''}
								</>
							}
							value={<Money value={(p?.rate || 0) * (l.quantity || 0)} />}
							meta={
								balance?.excess
									? 'Перерасход ' + nf.format(balance.excess) + ' ' + unit(p?.unit || '')
									: changed
										? 'Изменено'
										: p?.section
							}
							attention={!p || !!balance?.excess}
							hint="Правки остаются в черновике до подтверждения отчёта."
						>
							<section className="work-card work-detail">
								<div className="work-card-heading">
									<button
										className="work-name"
										onClick={() => {
											setReplaceIndex(i);
											setWorkPicker(true);
										}}
									>
										<b>{p ? 'Заменить работу' : 'Выберите работу'}</b>
										<small>{p?.section || l.reason || l.raw}</small>
									</button>
									<button
										className="plain-icon"
										aria-label={'Удалить работу ' + (i + 1)}
										onClick={() =>
											confirmRemoval(
												{
													name: p?.name || l.raw || 'Работа',
													quantity: l.quantity,
													unit: p?.unit,
													saved: !!(l.item_id && oldLines[l.item_id]),
												},
												() => setLines((ls) => ls.filter((line) => line !== l)),
											)
										}
									>
										<Trash2 size={16} />
									</button>
								</div>
								{l.raw && <p className="recognized-text">{l.raw}</p>}
								{!p && <Alert type="warning" message="Нужен выбор позиции перед подтверждением" />}
								<div className="work-card-input">
									<label>
										Выполнено
										<div className="quantity-field">
											<InputNumber
												aria-label={'Объём работы ' + (i + 1)}
												controls={false}
												min={0.01}
												max={1e8}
												value={l.quantity}
												placeholder="0"
												onChange={(v) => patchLine(i, v)}
											/>
											<span>{p ? unit(p.unit) : 'ед.'}</span>
										</div>
									</label>
									<div className="work-value">
										<span>Стоимость работы</span>
										<strong>
											<Money value={(p?.rate || 0) * (l.quantity || 0)} />
										</strong>
									</div>
								</div>
								{p && balance && <WorkEstimate balance={balance} unit={p.unit} />}
								{p && (
									<ReportNoteButton
										userId={session.user.telegram_id}
										key={`${day}:${p.id}`}
										project={project}
										scope={`work-note:${day}:${p.id}`}
										value={l.note || ''}
										label="Примечание к работе"
										onChange={(note) => {
											setLines((items) =>
												items.map((item, index) => (index === i ? { ...item, note } : item)),
											);
										}}
									/>
								)}
								<div className="work-card-foot">
									<span>
										{p ? (
											<>
												<Money value={p.rate} /> / {unit(p.unit)}
											</>
										) : (
											'Уточните позицию'
										)}
									</span>
									{changed && <Tag color="blue">Изменено</Tag>}
								</div>
							</section>
						</CompactWorkEditor>
					);
				})}
			</div>
			{!lines.length && !parsed.length && !parsing && positions.length > 0 && (
				<div className="no-work">
					<p>Добавьте работы, выполненные за день</p>
				</div>
			)}
			{deltaIds.length > 0 && report?.revision! > 0 && (
				<section className="change-preview">
					<h3>Изменения к подтверждению</h3>
					{deltaIds.map(
						(id) =>
							byId[id] && (
								<div key={id}>
									<span>{shortName(byId[id])}</span>
									<b>
										{nf.format(oldLines[id] || 0)} → {nf.format(nextLines[id] || 0)}{' '}
										{unit(byId[id].unit)}
									</b>
								</div>
							),
					)}
				</section>
			)}
			{report && report.revision > 0 && (
				<div className="current-status">
					<Button
						type="text"
						size="small"
						icon={<RotateCcw size={14} />}
						disabled={busy}
						onClick={() => void restoreDay()}
					>
						Вернуть к началу дня
					</Button>
					{report.sync_status !== 'synced' &&
						data.config.source === 'bitrix' &&
						data.config.has_webhook && (
							<Button size="small" loading={busy} onClick={() => void retry(day)}>
								Повторить отправку
							</Button>
						)}
					{report.sync_status === 'error' && report.sync_error && (
						<Alert
							type="warning"
							showIcon
							message="Нужно проверить изменения таблицы"
							description={report.sync_error}
							action={
								<Button size="small" onClick={() => openObjectSection('table')}>
									Проверить таблицу
								</Button>
							}
						/>
					)}
					{report.sync_status === 'synced' && report.sync_error && (
						<Alert type="warning" showIcon message={report.sync_error} />
					)}
				</div>
			)}
			<div className="confirm-bar">
				<div>
					<span>
						{parsed.length
							? 'Черновик отчёта'
							: dirty
								? 'Есть неподтверждённые изменения'
								: 'Отчёт без изменений'}
					</span>
					<strong>
						<Money value={amount} />
					</strong>
				</div>
				<Button
					type="primary"
					size="large"
					icon={<Check size={18} />}
					disabled={
						parsing ||
						parsedCrewAmbiguous ||
						(parsed.length ? parsedIncomplete > 0 : !valid || (!dirty && !!report?.revision))
					}
					loading={busy}
					onClick={parsed.length ? confirmParsedReport : confirm}
				>
					{busy ? 'Сохраняем…' : 'Подтвердить'}
				</Button>
			</div>
		</>
	);
}
