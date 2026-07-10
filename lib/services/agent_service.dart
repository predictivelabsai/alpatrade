import 'package:carhero/models/agent.dart';
import 'package:carhero/services/api_client.dart';

class AgentService {
  final ApiClient _client;

  AgentService(this._client);

  Future<List<AgentOut>> listAgents() async {
    final list = await _client.getList('/agents');
    return list
        .map((e) => AgentOut.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}
