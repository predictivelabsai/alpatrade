import 'dart:async';

import 'package:dio/dio.dart';
import 'package:alpatrade/config/api_config.dart';

/// Raised when a protected endpoint rejects the stored bearer session.
class UnauthorizedException implements Exception {
  final String message;
  const UnauthorizedException([this.message = 'Unauthorized']);

  @override
  String toString() => 'UnauthorizedException: $message';
}

bool isUnauthorizedError(Object error) {
  return error is UnauthorizedException ||
      (error is DioException && error.error is UnauthorizedException);
}

/// Thin Dio wrapper over the AlpaTrade REST API. Public calls may be anonymous;
/// protected calls receive the persisted bearer token.
class ApiClient {
  final Dio _dio;

  ApiClient({
    String? token,
    FutureOr<void> Function()? onUnauthorized,
    HttpClientAdapter? adapter,
  }) : _dio = Dio(
         BaseOptions(
           baseUrl: ApiConfig.baseUrl,
           connectTimeout: ApiConfig.connectTimeout,
           receiveTimeout: ApiConfig.receiveTimeout,
           headers: {
             'Content-Type': 'application/json',
             if (token != null && token.isNotEmpty)
               'Authorization': 'Bearer $token',
           },
         ),
       ) {
    if (adapter != null) _dio.httpClientAdapter = adapter;
    _dio.interceptors.add(
      InterceptorsWrapper(
        onError: (error, handler) async {
          if (error.response?.statusCode == 401) {
            await onUnauthorized?.call();
            handler.reject(
              DioException(
                requestOptions: error.requestOptions,
                response: error.response,
                error: const UnauthorizedException(),
                type: DioExceptionType.badResponse,
              ),
            );
            return;
          }
          handler.next(error);
        },
      ),
    );
  }

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      path,
      queryParameters: queryParameters,
    );
    return response.data!;
  }

  Future<List<dynamic>> getList(
    String path, {
    Map<String, dynamic>? queryParameters,
  }) async {
    final response = await _dio.get<List<dynamic>>(
      path,
      queryParameters: queryParameters,
    );
    return response.data!;
  }

  Future<Map<String, dynamic>> post(String path, {dynamic data}) async {
    final response = await _dio.post<Map<String, dynamic>>(path, data: data);
    return response.data!;
  }
}
