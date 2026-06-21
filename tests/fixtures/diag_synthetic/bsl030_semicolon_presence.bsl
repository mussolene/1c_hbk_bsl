// Synthetic contract for BSL030 SemicolonPresence.
// Comments mark diagnostics expected on following BSL lines.

Процедура ПроверитьОператоры()

	// OK: assignment has terminator.
	Значение = 1;

	// EXPECT: BSL030
	Значение = 1

	// OK: call has terminator.
	Сообщить("ok");

	// EXPECT: BSL030
	Сообщить("missing")

	// OK: while statement has terminator after КонецЦикла.
	Пока Условие Цикл
		Обработать();
	КонецЦикла;

	// EXPECT: BSL030 +3
	Пока Условие Цикл
		Обработать();
	КонецЦикла

	// OK: standalone semicolon belongs to BSL025, not BSL030.
	;

КонецПроцедуры

Функция ПроверитьВозвраты()

	// EXPECT: BSL030
	Возврат "строка"

КонецФункции

Функция ПроверитьМногострочнуюСтроку()

	// EXPECT: BSL030 +2
	Значение = "Первая строка
	|Вторая строка"

	Возврат Значение;

КонецФункции
