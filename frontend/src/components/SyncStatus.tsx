import { CheckCheck, Clock3, RefreshCw } from 'lucide-react';
export function Status({ status }: { status: string }) {
	return (
		<span className={'sync-status ' + status}>
			{status === 'synced' ? (
				<CheckCheck size={13} />
			) : status === 'error' ? (
				<RefreshCw size={13} />
			) : (
				<Clock3 size={13} />
			)}
			<span>
				{status === 'synced'
					? 'В Битрикс24'
					: status === 'error'
						? 'Ошибка отправки'
						: status === 'pending'
							? 'Ожидает отправки'
							: status === 'imported'
								? 'Из таблицы'
								: 'Не отправлен'}
			</span>
		</span>
	);
}
