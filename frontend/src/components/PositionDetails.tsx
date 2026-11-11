import { Alert, Button, Empty, Input, Modal, Select, Spin, Tabs } from 'antd';
import { Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import dayjs from '../lib/date';
import { Money, nf, unit } from '../lib/format';
import type { Position, PositionHistory } from '../types';

const historyLabels: Record<string, string> = {
	report: 'Изменён отчёт',
	report_restore: 'Возврат к началу дня',
	bitrix_day: 'Объём за день в Битрикс24',
	bitrix_values: 'Итоги в Битрикс24',
	estimate: 'Обновлена смета',
	hide: 'Скрыта из подбора',
	show: 'Возвращена в подбор',
	link: 'Привязана работа',
	unlink: 'Связь с работой удалена',
};
const fieldLabels: Record<string, string> = {
	name: 'Название',
	planned: 'План',
	completed: 'Выполнено',
	remaining: 'Остаток',
	rate: 'Расценка',
	unit: 'Единица',
};
type Advice = { answer: string; checks: string[] };

export function positionOverrun(position: Position) {
	return Math.max(0, -position.remaining, -(position.bitrix?.remaining ?? 0));
}

export function PositionDetails({
	workspace,
	position,
	close,
	manage,
}: {
	workspace: WorkspaceView;
	position: Position;
	close: () => void;
	manage: (position: Position) => void;
}) {
	const { project, allPositions, byId, refresh, session } = workspace;
	const [history, setHistory] = useState<PositionHistory | null>(null);
	const [error, setError] = useState('');
	const [historyVersion, setHistoryVersion] = useState(0);
	const [linkedWork, setLinkedWork] = useState(position.linked_work_id || undefined);
	const [linkBusy, setLinkBusy] = useState(false);
	const [linkError, setLinkError] = useState('');
	const [question, setQuestion] = useState('');
	const [advice, setAdvice] = useState<Advice | null>(null);
	const [consulting, setConsulting] = useState(false);
	const [adviceError, setAdviceError] = useState('');
	const endpoint = '/object/positions/' + encodeURIComponent(position.id);
	const measurement = unit(position.unit);
	const overrun = positionOverrun(position);
	const source = position.bitrix;
	const linked = position.linked_work_id ? byId[position.linked_work_id] : null;
	const quantity = (value: number) => nf.format(value) + ' ' + measurement;
	useEffect(() => {
		const controller = new AbortController();
		setError('');
		request<PositionHistory>(endpoint + '/history', undefined, project, controller.signal)
			.then((result) => {
				if (!controller.signal.aborted) setHistory(result);
			})
			.catch((failure) => {
				if (!controller.signal.aborted) setError((failure as Error).message);
			});
		return () => controller.abort();
	}, [endpoint, project, historyVersion]);

	const saveLink = async () => {
		setLinkBusy(true);
		setLinkError('');
		try {
			await request(endpoint + '/link', { work_id: linkedWork || null }, project);
			await refresh(true);
			setHistoryVersion((value) => value + 1);
		} catch (failure) {
			setLinkError((failure as Error).message);
		} finally {
			setLinkBusy(false);
		}
	};
	const consult = async () => {
		setConsulting(true);
		setAdviceError('');
		try {
			setAdvice(await request<Advice>(endpoint + '/consult', { question }, project));
		} catch (failure) {
			setAdviceError((failure as Error).message);
		} finally {
			setConsulting(false);
		}
	};
	const displayValue = (field: string, value: number | string) =>
		field === 'rate' && typeof value === 'number' ? (
			<Money value={value} />
		) : typeof value === 'number' ? (
			quantity(value)
		) : (
			value
		);
	return (
		<Modal open title={position.name} onCancel={close} footer={null} width={650}>
			<div className="position-details">
				<div className="position-totals">
					<span>
						План <b>{quantity(position.planned)}</b>
					</span>
					<span>
						Выполнено <b>{quantity(position.completed)}</b>
					</span>
					<span>
						Остаток <b>{quantity(position.remaining)}</b>
					</span>
				</div>
				{source && (
					<p className="position-source">
						В Битрикс24 · план {quantity(source.planned)} · выполнено {quantity(source.completed)} ·
						остаток <b>{quantity(source.remaining)}</b>
					</p>
				)}
				{(overrun > 0 || position.hidden) && (
					<Alert
						type="warning"
						showIcon
						icon={<TriangleAlert size={18} />}
						message={
							position.hidden ? 'Позиция скрыта из подбора' : 'Перерасход ' + quantity(overrun)
						}
						description={
							position.hidden
								? 'Смета и история доступны.'
								: 'Если работу больше не нужно предлагать при заполнении отчёта, её можно скрыть из подбора.'
						}
						action={
							<Button size="small" onClick={() => manage(position)}>
								{position.hidden ? 'Вернуть в подбор' : 'Скрыть из подбора'}
							</Button>
						}
					/>
				)}
				{linked && (
					<p>
						<b>Связанная работа</b> · {linked.name}
					</p>
				)}
				<Tabs
					items={[
						{
							key: 'history',
							label: 'История',
							children: (
								<div className="position-history">
									{error && <Alert type="error" showIcon message={error} />}
									{!history && !error && <Spin size="small" />}
									{history?.events.map((event, index) => (
										<section key={event.created_at + ':' + index}>
											<b>{historyLabels[event.kind] || 'Изменение'}</b>
											<small>
												{dayjs(event.date).format('D MMM YYYY')} {event.actor && '· ' + event.actor}
											</small>
											{event.before !== undefined && event.after !== undefined && (
												<p>
													{quantity(event.before)} → <strong>{quantity(event.after)}</strong>
												</p>
											)}
											{event.work && <p>{event.work}</p>}
											{event.values &&
												Object.entries(event.values.after).map(([field, after]) => {
													const before = event.values?.before[field];
													return before !== undefined && before !== after ? (
														<p key={field}>
															{fieldLabels[field] || field} · {displayValue(field, before)} →{' '}
															{displayValue(field, after)}
														</p>
													) : null;
												})}
										</section>
									))}
									{!!history?.days.length && (
										<details>
											<summary>Объёмы по дням · {history.days.length}</summary>
											{history.days.map((entry) => (
												<p key={entry.date}>
													{dayjs(entry.date).format('D MMM YYYY')} ·{' '}
													<b>{quantity(entry.quantity)}</b>
													{entry.sync_status === null ? ' · из таблицы' : ''}
												</p>
											))}
										</details>
									)}
									{history && !history.events.length && !history.days.length && (
										<Empty
											description="Изменений по позиции пока нет"
											image={Empty.PRESENTED_IMAGE_SIMPLE}
										/>
									)}
								</div>
							),
						},
						{
							key: 'link',
							label: 'Связать работу',
							children: (
								<div className="position-history">
									<Select
										aria-label="Связанная работа"
										placeholder="Выберите работу из сметы"
										showSearch
										allowClear
										optionFilterProp="label"
										value={linkedWork}
										onChange={setLinkedWork}
										options={allPositions
											.filter((item) => item.id !== position.id)
											.map((item) => ({ value: item.id, label: item.name }))}
									/>
									{linkError && <Alert type="error" showIcon message={linkError} />}
									<Button
										type="primary"
										loading={linkBusy}
										disabled={(linkedWork || null) === (position.linked_work_id || null)}
										onClick={saveLink}
									>
										Сохранить связь
									</Button>
								</div>
							),
						},
						{
							key: 'ai',
							label: 'Консультация ИИ',
							children: (
								<div className="position-history">
									<Input.TextArea
										aria-label="Вопрос по позиции"
										value={question}
										onChange={(event) => setQuestion(event.target.value)}
										maxLength={1000}
										autoSize={{ minRows: 2, maxRows: 5 }}
										placeholder="Например, почему остаток отрицательный?"
									/>
									<Button
										icon={<Sparkles size={16} />}
										type="primary"
										loading={consulting}
										disabled={!session.ai_connected}
										onClick={consult}
									>
										Проверить с ИИ
									</Button>
									{!session.ai_connected && (
										<small>Администратор может подключить ИИ в настройках.</small>
									)}
									{adviceError && <Alert type="warning" showIcon message={adviceError} />}
									{advice && (
										<section>
											<p>{advice.answer}</p>
											{advice.checks.length > 0 && (
												<ul>
													{advice.checks.map((check, index) => (
														<li key={index}>{check}</li>
													))}
												</ul>
											)}
										</section>
									)}
								</div>
							),
						},
					]}
				/>
			</div>
		</Modal>
	);
}
