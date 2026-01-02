namespace Smoothment.Commands.Synonym;

public record SynonymCommandOptions(
    string TargetType,
    string Name,
    string SynonymToAdd);
