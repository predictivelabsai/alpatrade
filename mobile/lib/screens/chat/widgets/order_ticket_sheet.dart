import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:alpatrade/config/theme.dart';
import 'package:alpatrade/models/order.dart';
import 'package:alpatrade/providers/order_provider.dart';
import 'package:alpatrade/providers/positions_provider.dart';
import 'package:alpatrade/utils/formatters.dart';

/// Paper-order ticket. Opened from the quick-order cards; submits to POST /v2/order.
class OrderTicketSheet extends ConsumerStatefulWidget {
  final String side; // 'buy' | 'sell'
  final String orderType; // 'market' | 'limit'
  final String? symbol;

  const OrderTicketSheet({
    super.key,
    this.side = 'buy',
    this.orderType = 'market',
    this.symbol,
  });

  @override
  ConsumerState<OrderTicketSheet> createState() => _OrderTicketSheetState();
}

class _OrderTicketSheetState extends ConsumerState<OrderTicketSheet> {
  late String _side = widget.side;
  late String _orderType = widget.orderType;
  late final _symbolCtrl = TextEditingController(text: widget.symbol ?? '');
  final _qtyCtrl = TextEditingController(text: '1');
  final _limitCtrl = TextEditingController();

  bool _submitting = false;
  OrderResponse? _result;
  String? _error;

  bool get _isLimit => _orderType == 'limit';

  @override
  void dispose() {
    _symbolCtrl.dispose();
    _qtyCtrl.dispose();
    _limitCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final symbol = _symbolCtrl.text.trim().toUpperCase();
    final qty = double.tryParse(_qtyCtrl.text.trim());
    final limit = double.tryParse(_limitCtrl.text.trim());

    if (symbol.isEmpty) {
      return setState(() => _error = 'Enter a symbol');
    }
    if (qty == null || qty <= 0) {
      return setState(() => _error = 'Enter a valid quantity');
    }
    if (_isLimit && (limit == null || limit <= 0)) {
      return setState(() => _error = 'Enter a valid limit price');
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    try {
      final res = await ref
          .read(orderServiceProvider)
          .placeOrder(
            OrderRequest(
              symbol: symbol,
              qty: qty,
              side: _side,
              orderType: _orderType,
              limitPrice: _isLimit ? limit : null,
            ),
          );
      if (!mounted) return;
      if (res.ok) {
        ref.invalidate(positionsProvider);
        setState(() => _result = res);
      } else {
        setState(() => _error = res.error ?? 'Order rejected');
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;
    return Padding(
      padding: EdgeInsets.only(bottom: bottomInset),
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 20),
        decoration: BoxDecoration(
          color: AppTheme.bg,
          borderRadius: const BorderRadius.vertical(top: Radius.circular(18)),
        ),
        child: _result != null ? _buildResult(_result!) : _buildForm(),
      ),
    );
  }

  Widget _grabber() => Center(
    child: Container(
      margin: const EdgeInsets.only(bottom: 12),
      width: 40,
      height: 4,
      decoration: BoxDecoration(
        color: AppTheme.lineBr,
        borderRadius: BorderRadius.circular(2),
      ),
    ),
  );

  Widget _buildForm() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _grabber(),
        Row(
          children: [
            Text(
              'New paper order',
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: AppTheme.ink,
              ),
            ),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: AppTheme.accentDim,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                'PAPER',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.accentDeep,
                  letterSpacing: 0.5,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        // Buy / Sell
        _SegToggle(
          options: const ['buy', 'sell'],
          labels: const ['Buy', 'Sell'],
          value: _side,
          activeColor: _side == 'buy' ? AppTheme.gain : AppTheme.loss,
          onChanged: (v) => setState(() => _side = v),
        ),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              flex: 3,
              child: _field(
                label: 'Symbol',
                controller: _symbolCtrl,
                hint: 'AAPL',
                textCapitalization: TextCapitalization.characters,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              flex: 2,
              child: _field(
                label: 'Quantity',
                controller: _qtyCtrl,
                hint: '1',
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                inputFormatters: [
                  FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        // Market / Limit
        _SegToggle(
          options: const ['market', 'limit'],
          labels: const ['Market', 'Limit'],
          value: _orderType,
          activeColor: AppTheme.accent,
          onChanged: (v) => setState(() => _orderType = v),
        ),
        if (_isLimit) ...[
          const SizedBox(height: 12),
          _field(
            label: 'Limit price',
            controller: _limitCtrl,
            hint: '150.00',
            prefix: r'$ ',
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
            ],
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: AppTheme.loss, fontSize: 13)),
        ],
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: _submitting ? null : _submit,
            style: ElevatedButton.styleFrom(
              backgroundColor: _side == 'buy' ? AppTheme.gain : AppTheme.loss,
            ),
            child: _submitting
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : Text(
                    '${_side == 'buy' ? 'Buy' : 'Sell'} '
                    '${_isLimit ? '(limit)' : '(market)'}',
                  ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          'Simulated paper order — not investment advice.',
          style: TextStyle(fontSize: 11, color: AppTheme.inkDim),
        ),
      ],
    );
  }

  Widget _buildResult(OrderResponse r) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _grabber(),
        Row(
          children: [
            Icon(Icons.check_circle, color: AppTheme.gain, size: 22),
            const SizedBox(width: 8),
            Text(
              'Order placed',
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: AppTheme.ink,
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        _resultRow('Symbol', r.symbol ?? '—'),
        _resultRow('Side', (r.side ?? _side).toUpperCase()),
        _resultRow('Type', (r.orderType ?? _orderType).toUpperCase()),
        _resultRow('Quantity', Fmt.shares(r.qty)),
        if (r.limitPrice != null) _resultRow('Limit', Fmt.usd(r.limitPrice)),
        _resultRow('Status', r.status ?? '—'),
        if (r.orderId != null) _resultRow('Order ID', r.orderId!, mono: true),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          height: 48,
          child: ElevatedButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Done'),
          ),
        ),
      ],
    );
  }

  Widget _resultRow(String label, String value, {bool mono = false}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      children: [
        Text(label, style: TextStyle(fontSize: 13, color: AppTheme.inkDim)),
        const Spacer(),
        Flexible(
          child: Text(
            value,
            textAlign: TextAlign.right,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppTheme.ink,
              fontFamily: mono ? AppTheme.monoFont : null,
            ),
          ),
        ),
      ],
    ),
  );

  Widget _field({
    required String label,
    required TextEditingController controller,
    String? hint,
    String? prefix,
    TextInputType? keyboardType,
    TextCapitalization textCapitalization = TextCapitalization.none,
    List<TextInputFormatter>? inputFormatters,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: AppTheme.inkMuted,
          ),
        ),
        const SizedBox(height: 5),
        TextField(
          controller: controller,
          keyboardType: keyboardType,
          textCapitalization: textCapitalization,
          inputFormatters: inputFormatters,
          style: TextStyle(
            fontFamily: AppTheme.monoFont,
            fontSize: 15,
            color: AppTheme.ink,
          ),
          decoration: InputDecoration(
            hintText: hint,
            prefixText: prefix,
            isDense: true,
          ),
        ),
      ],
    );
  }
}

class _SegToggle extends StatelessWidget {
  final List<String> options;
  final List<String> labels;
  final String value;
  final Color activeColor;
  final ValueChanged<String> onChanged;

  const _SegToggle({
    required this.options,
    required this.labels,
    required this.value,
    required this.activeColor,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppTheme.bgRaise,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.line),
      ),
      child: Row(
        children: [
          for (var i = 0; i < options.length; i++)
            Expanded(
              child: GestureDetector(
                onTap: () => onChanged(options[i]),
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 150),
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  decoration: BoxDecoration(
                    color: value == options[i]
                        ? activeColor
                        : Colors.transparent,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    labels[i],
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: value == options[i]
                          ? Colors.white
                          : AppTheme.inkMuted,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
