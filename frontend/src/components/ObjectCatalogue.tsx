import { Alert, Button, Empty, Input, Spin, Tag } from 'antd';
import { Eye, EyeOff, Search, Trash2 } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { Money, nf, unit } from '../lib/format';
import type { ObjectManagement, Position } from '../types';

export function ObjectCatalogue({
	workspace,
	management,
	error,
	onManage,
}: {
	workspace: WorkspaceView;
	management: ObjectManagement | null;
	error: string;
	onManage: (position: Position) => void;
}) {
	const [query, setQuery] = useState('');
	const { allPositions, positions, openObjectSection } = workspace;
	const term = query.trim().toLocaleLowerCase('ru');
	const matching = allPositions.filter((position) =>
		[position.name, position.section, position.source_sheet]
			.filter(Boolean)
			.join(' ')
			.toLocaleLowerCase('ru')
			.includes(term),
	);
	if (!allPositions.length) {
		return (
			<section className="object-panel">
				<Empty description="Смета пуста" image={Empty.PRESENTED_IMAGE_SIMPLE} />
				<Button type="primary" onClick={() => openObjectSection('table')}>
					Добавить таблицу
				</Button>
			</section>
		);
	}
	return (
		<section className="object-panel">
			<div className="object-panel-heading">
				<h2>Смета</h2>
				<Tag>
					{positions.length} из {allPositions.length} в подборе
				</Tag>
			</div>
			<Input
				aria-label="Найти работу в смете"
				placeholder="Название работы"
				prefix={<Search size={17} />}
				allowClear
				value={query}
				onChange={(event) => setQuery(event.target.value)}
			/>
			{error && <Alert type="warning" showIcon message={error} />}
			{!management && !error && <Spin size="small" />}
			{!matching.length && (
				<Empty description="Работы не найдены" image={Empty.PRESENTED_IMAGE_SIMPLE} />
			)}
			<ul className="object-catalogue">
				{matching.map((position) => {
					const used = management?.used_positions.includes(position.id);
					const label = position.hidden
						? 'Вернуть в подбор'
						: used
							? 'Скрыть из подбора'
							: 'Удалить из сметы';
					const Icon = position.hidden ? Eye : used ? EyeOff : Trash2;
					return (
						<li key={position.id}>
							<div>
								<b>{position.name}</b>
								<small>
									<Money value={position.rate} /> / {unit(position.unit)} · Остаток{' '}
									{nf.format(position.remaining)} {unit(position.unit)}
								</small>
							</div>
							{position.hidden && <Tag color="gold">Скрыта</Tag>}
							<Button
								size="small"
								danger={!position.hidden && !used}
								disabled={!management}
								aria-label={label + ' — ' + position.name}
								title={label}
								icon={<Icon size={17} />}
								onClick={() => onManage(position)}
							/>
						</li>
					);
				})}
			</ul>
			{positions.length > 0 && !workspace.active?.work_dates?.length && (
				<Button type="primary" onClick={() => openObjectSection('reports')}>
					Заполнить первый отчёт
				</Button>
			)}
		</section>
	);
}
