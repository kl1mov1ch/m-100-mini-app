import { Alert, Button, Empty, InputNumber, Spin, Tag } from 'antd';
import 'dayjs/locale/ru';
import { Check, FileSpreadsheet, Mic, Plus, Trash2, Users } from 'lucide-react';
import { DatePicker } from '../components/ResponsiveDatePicker';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { LinkedTable } from '../components/LinkedTable';
import { Status } from '../components/SyncStatus';
import { Money, nf, shortName, unit } from '../lib/format';
export function DailyReportPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		session,
		data,
		busy,
		day,
		report,
		lines,
		setLines,
		crew,
		setCrew,
		setWorkPicker,
		setReplaceIndex,
		setTextOpen,
		active,
		positions,
		byId,
		changeDay,
		patchLine,
		amount,
		each,
		extra,
		oldLines,
		nextLines,
		deltaIds,
		dirty,
		valid,
		confirm,
		retry,
		openSettings,
	} = workspace;
	return !data ? (
		<div className="empty-panel">
			{active ? <Spin /> : <Empty description="Сначала добавьте объект" />}
		</div>
	) : (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{active?.name}</span>
					<h1>Дневной отчёт</h1>
				</div>
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
			{positions.length > 0 && (
				<LinkedTable config={data.config} positions={positions.length} onSettings={openSettings} />
			)}
			<section className="daily-earnings">
				<div className="earnings-total">
					<span>Выработка за день</span>
					<strong>
						<Money value={amount} />
					</strong>
					<small>{lines.length} работ по расценкам вашей сметы</small>
				</div>
				<div className="crew-control">
					<span>
						<Users size={16} /> Работников на объекте
					</span>
					<InputNumber
						aria-label="Количество работников"
						min={1}
						max={1000}
						precision={0}
						value={crew}
						onChange={(v) => setCrew(v || 1)}
					/>
				</div>
				<div className="earnings-person">
					<span>На одного человека</span>
					<strong>
						<Money value={each} />
					</strong>
				</div>
				{extra > 0 && (
					<div className="rounding-note">
						{extra} чел. получат по <Money value={each + 0.01} /> для распределения до копейки.
					</div>
				)}
			</section>
			<div className="report-toolbar">
				<Button
					type="primary"
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
					icon={<Mic size={17} />}
					onClick={() => setTextOpen(true)}
					disabled={!positions.length}
				>
					Текстом или голосом
				</Button>
			</div>
			{!positions.length && (
				<div className="empty-panel">
					<FileSpreadsheet size={34} />
					<h2>Добавьте таблицу объекта</h2>
					<p>Загрузите файл или подключите таблицу Битрикс24</p>
					<Button type="primary" onClick={openSettings}>
						Добавить таблицу
					</Button>
				</div>
			)}
			<div className="work-list">
				{lines.map((l, i) => {
					const p = l.item_id ? byId[l.item_id] : null;
					const changed = p && oldLines[p.id] !== l.quantity;
					return (
						<section className={'work-card ' + (!p ? 'needs-review' : '')} key={i}>
							<div className="work-card-heading">
								<span className="work-index">{String(i + 1).padStart(2, '0')}</span>
								<button
									className="work-name"
									onClick={() => {
										setReplaceIndex(i);
										setWorkPicker(true);
									}}
								>
									<b>{p ? shortName(p) : 'Выберите работу'}</b>
									<small>{p?.section || l.reason || l.raw}</small>
								</button>
								<button
									className="plain-icon"
									aria-label={'Удалить работу ' + (i + 1)}
									onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}
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
							<div className="work-card-foot">
								<span>
									{p ? (
										<>
											<Money value={p.rate} /> / {unit(p.unit)} <i />
											Остаток {nf.format(p.remaining)} {unit(p.unit)}
										</>
									) : (
										'Уточните позицию'
									)}
								</span>
								{changed && <Tag color="blue">Изменено</Tag>}
							</div>
						</section>
					);
				})}
			</div>
			{!lines.length && positions.length > 0 && (
				<div className="no-work">
					<FileSpreadsheet size={29} />
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
					<Status status={report.sync_status} />
					{report.sync_status !== 'synced' && (
						<Button size="small" loading={busy} onClick={() => void retry(day)}>
							Повторить отправку
						</Button>
					)}
					{report.sync_status === 'error' && report.sync_error && <p>{report.sync_error}</p>}
				</div>
			)}
			<div className="confirm-bar">
				<div>
					<span>{dirty ? 'Есть неподтверждённые изменения' : 'Отчёт без изменений'}</span>
					<strong>
						<Money value={amount} />
					</strong>
				</div>
				<Button
					type="primary"
					size="large"
					icon={<Check size={18} />}
					disabled={!valid || (!dirty && !!report?.revision)}
					loading={busy}
					onClick={confirm}
				>
					{busy ? 'Сохраняем…' : 'Подтвердить'}
				</Button>
			</div>
		</>
	);
}
