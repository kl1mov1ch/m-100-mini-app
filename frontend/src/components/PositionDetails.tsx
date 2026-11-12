import { Alert, Button, Empty, Input, Modal, Spin, Tabs } from 'antd';
import { Settings2, Sparkles, Trash2, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import dayjs from '../lib/date';
import { Money } from '../lib/format';
import { estimateStatus, formatVolume, positionOverrun } from '../lib/position-volume';
import { useHorizontalSwipe } from '../hooks/useHorizontalSwipe';
import type { CatalogueAction, Position, PositionHistory } from '../types';

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

export function PositionDetails({
	workspace,
	position,
	close,
	manage,
}: {
	workspace: WorkspaceView;
	position: Position;
	close: () => void;
	manage: (position: Position, action: CatalogueAction) => void;
}) {
	const { project, data, session } = workspace;
	const [history, setHistory] = useState<PositionHistory | null>(null);
	const [error, setError] = useState('');
	const [question, setQuestion] = useState('');
	const [advice, setAdvice] = useState<Advice | null>(null);
	const [consulting, setConsulting] = useState(false);
	const [adviceError, setAdviceError] = useState('');
	const endpoint = '/object/positions/' + encodeURIComponent(position.id);
	const [tab, setTab] = useState('history');
	const overrun = positionOverrun(position);
	const source = position.bitrix;
	const quantity = (value: number) => formatVolume(value, position.unit);
	const missingBitrix =
		data?.config.source === 'bitrix' &&
		(!source || data.config.bitrix_read?.status === 'unavailable');
	const activeTab = tab === 'ai' && !missingBitrix ? 'history' : tab;
	const tabs = missingBitrix ? ['history', 'settings', 'ai'] : ['history', 'settings'];
	const tabSwipe = useHorizontalSwipe((step) => {
		const next = tabs[tabs.indexOf(activeTab) + step];
		if (next) setTab(next);
	});
	const recalculated = overrun ? overrun.planned - overrun.completed : 0;
	const inconsistent = overrun && Math.abs(overrun.remaining - recalculated) > 0.0001;

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
	}, [endpoint, project, position.hidden]);

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
			<div className="position-details swipe-surface" {...tabSwipe}>
				<div className="position-totals">
					<span>
						План <b>{quantity(position.planned)}</b>
					</span>
					<span>
						Выполнено <b>{quantity(position.completed)}</b>
					</span>
					<span>
						<b>{estimateStatus(position, position.unit)}</b>
					</span>
				</div>
				{source && (
					<p className="position-source">
						{data?.config.bitrix_read?.status === 'unavailable'
							? 'Последнее чтение Битрикс24'
							: 'Битрикс24'}{' '}
						· план {quantity(source.planned)} · выполнено {quantity(source.completed)} ·{' '}
						<b>{estimateStatus(source, position.unit)}</b>
					</p>
				)}
				{overrun && (
					<Alert
						type="warning"
						showIcon
						icon={<TriangleAlert size={18} />}
						message={
							overrun.completed > overrun.planned
								? estimateStatus(overrun, position.unit)
								: 'Проверьте остаток'
						}
						description={
							<>
								<p>
									{overrun.fromBitrix ? 'Битрикс24' : 'Приложение'} · план{' '}
									{quantity(overrun.planned)} · выполнено {quantity(overrun.completed)}.
								</p>
								{inconsistent ? (
									<p>Значение остатка в таблице расходится с планом и фактом. Проверьте формулу.</p>
								) : null}
							</>
						}
					/>
				)}
				{position.hidden && <p className="position-source">Позиция скрыта из подбора.</p>}
				<Tabs
					activeKey={activeTab}
					onChange={setTab}
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
							key: 'settings',
							label: 'Настройки',
							icon: <Settings2 size={15} />,
							children: (
								<div className="position-history">
									{(overrun || position.hidden) && (
										<Button onClick={() => manage(position, position.hidden ? 'show' : 'hide')}>
											{position.hidden ? 'Вернуть в подбор' : 'Скрыть из подбора'}
										</Button>
									)}
									<Button
										danger
										icon={<Trash2 size={16} />}
										disabled={!history?.can_delete}
										onClick={() => manage(position, 'delete')}
									>
										Удалить из сметы
									</Button>
									{history && !history.can_delete && (
										<small>Позиция используется в истории. Удаление недоступно.</small>
									)}
									{error && <Alert type="warning" showIcon message={error} />}
								</div>
							),
						},
						...(missingBitrix
							? [
									{
										key: 'ai',
										label: 'Помощь ИИ',
										children: (
											<div className="position-history">
												<Alert
													type="warning"
													showIcon
													message="Актуальные данные Битрикс24 по позиции пока не загружены"
												/>
												<Input.TextArea
													aria-label="Вопрос по позиции"
													value={question}
													onChange={(event) => setQuestion(event.target.value)}
													maxLength={1000}
													autoSize={{ minRows: 2, maxRows: 5 }}
													placeholder="Например, что проверить, если позиция не загрузилась?"
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
								]
							: []),
					]}
				/>
			</div>
		</Modal>
	);
}
